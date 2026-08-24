"""Run the pre-registered deep-drawdown rebound diagnostic on real local bars.

This script deliberately separates a useful historical diagnostic from trading
evidence.  The local daily-bar contract currently has
``strict_historical_pit=false`` and no historical quote/depth tape, so the
output can never promote a strategy.  It nevertheless computes the same fixed
event definition across the four asset sleeves, records unresolved events,
cost stress, and a chronological split so the missing evidence is explicit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from libs.data import store
from libs.data.universe import A_SHARE_LIQUID, US_LIQUID, altcoin_pairs
from libs.data.run_manifest import pin


CONFIG_PATH = Path("config/research/deep_drawdown_rebound.yaml")
REPORT_PATH = Path("data/deep_drawdown_rebound.json")
MANIFEST_PATH = Path("data/deep_drawdown_rebound.manifest.json")
OOS_FRACTION = 0.20
TRANCHE_OFFSETS = (0, 5, 20)
HORIZONS = (21, 63, 126, 252)
MIN_ASSET_CLUSTERS = 20
MIN_DATE_CLUSTERS = 20
US_REBOUND_SYMBOLS = tuple(dict.fromkeys((*US_LIQUID, "SNDK", "MU", "WDC", "MRVL")))


@dataclass(frozen=True)
class Sleeve:
    key: str
    symbols: tuple[str, ...]
    cost_bps: float


SLEEVES = (
    Sleeve("A_SHARE", tuple(A_SHARE_LIQUID), 40.0),
    Sleeve("US_EQUITY", US_REBOUND_SYMBOLS, 20.0),
    Sleeve("BTC", ("BTC-USDT",), 12.0),
    Sleeve("ALTCOIN", tuple(altcoin_pairs()), 35.0),
)


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if np.isfinite(parsed) and parsed > 0 else None


def _numeric(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if np.isfinite(parsed) else None


def _first_drawdown_events(frame) -> list[dict[str, Any]]:
    """Return one event per drawdown episode using only prior closes for peak."""
    if frame.empty:
        return []
    frame = frame.sort_values("event_date").drop_duplicates("event_date", keep="last")
    closes = np.array([_finite(v) for v in frame["close"]], dtype=object)
    dates = [str(v)[:10] for v in frame["event_date"]]
    prior_peak: float | None = None
    prior_triggered = False
    events: list[dict[str, Any]] = []
    for i, close in enumerate(closes):
        if close is None:
            continue
        drawdown = None if prior_peak is None else 1.0 - close / prior_peak
        triggered = drawdown is not None and drawdown >= 0.50
        if triggered and not prior_triggered:
            events.append({
                "event_index": i,
                "event_date": dates[i],
                "peak_close": round(float(prior_peak), 10),
                "event_close": round(float(close), 10),
                "drawdown": round(float(drawdown), 8),
            })
        prior_triggered = triggered
        prior_peak = max(prior_peak or close, close)
    return events


def _event_outcomes(frame, event: dict[str, Any], cost_bps: float) -> list[dict[str, Any]]:
    rows = frame.sort_values("event_date").drop_duplicates("event_date", keep="last").reset_index(drop=True)
    results: list[dict[str, Any]] = []
    event_index = int(event["event_index"])
    for horizon in HORIZONS:
        tranches: list[dict[str, Any]] = []
        for tranche, offset in enumerate(TRANCHE_OFFSETS, start=1):
            entry_index = event_index + 1 + offset
            exit_index = entry_index + horizon
            if exit_index >= len(rows):
                tranches.append({"tranche": tranche, "status": "unresolved", "reason": "insufficient_forward_bars"})
                continue
            entry = _finite(rows.iloc[entry_index].get("open"))
            exit_price = _finite(rows.iloc[exit_index].get("close"))
            if entry is None or exit_price is None:
                tranches.append({"tranche": tranche, "status": "unresolved", "reason": "missing_execution_price"})
                continue
            gross = exit_price / entry - 1.0
            net = gross - cost_bps / 10_000.0
            tranches.append({
                "tranche": tranche,
                "status": "diagnostic_fill",
                "entry_date": str(rows.iloc[entry_index]["event_date"])[:10],
                "exit_date": str(rows.iloc[exit_index]["event_date"])[:10],
                "gross_return": round(gross, 8),
                "net_return": round(net, 8),
            })
        resolved = [t for t in tranches if t["status"] == "diagnostic_fill"]
        results.append({
            "horizon_days": horizon,
            "tranches": tranches,
            "status": "diagnostic_fill" if len(resolved) == len(TRANCHE_OFFSETS) else "UNKNOWN",
            "gross_return": round(float(np.mean([t["gross_return"] for t in resolved])), 8) if resolved else None,
            "net_return": round(float(np.mean([t["net_return"] for t in resolved])), 8) if resolved else None,
            "cost_bps": cost_bps,
        })
    return results


def _summary(outcomes: list[dict[str, Any]], *, cost_multiple: float) -> dict[str, Any]:
    complete = [o for o in outcomes if o["status"] == "diagnostic_fill"]
    values = np.array([
        float(o["gross_return"]) - float(o.get("cost_bps", 0.0)) / 10_000.0 * cost_multiple
        for o in complete
    ], dtype=float)
    if not len(values):
        return {"n_complete": 0, "mean_net_return": None, "win_rate": None, "max_drawdown": None}
    equity = np.cumprod(1.0 + values)
    peaks = np.maximum.accumulate(equity)
    drawdown = float(np.max(1.0 - equity / peaks))
    return {
        "n_complete": int(len(values)),
        "n_unresolved": int(len(outcomes) - len(values)),
        "mean_net_return": round(float(values.mean()), 8),
        "median_net_return": round(float(np.median(values)), 8),
        "win_rate": round(float(np.mean(values > 0)), 8),
        "max_drawdown": round(drawdown, 8),
        "cost_multiple": cost_multiple,
    }


def _split(events: list[dict[str, Any]]) -> dict[str, Any]:
    dates = sorted({e["event_date"] for e in events})
    if len(dates) < 3:
        return {"status": "UNKNOWN", "reason": "fewer_than_three_event_dates", "dates": dates}
    cut = max(1, int(len(dates) * (1.0 - OOS_FRACTION)))
    return {
        "status": "UNKNOWN",
        "train_dates": dates[:cut],
        "oos_dates": dates[cut:],
        "reason": "strict_historical_pit_is_false_and_asset_date_cluster_floor_is_not_met",
    }


def _fundamental_quality(symbol: str, event_date: str, as_of) -> dict[str, Any]:
    """Evaluate row-level PIT evidence; missing acceptance is UNKNOWN.

    The dataset remains globally non-promotable because historical coverage and
    survivorship controls are incomplete.  A filing with an SEC acceptance
    timestamp can nevertheless be evaluated honestly for this event instead of
    being discarded merely because another older filing in the same symbol is
    unresolved.
    """
    frame = store.read(store.FUNDAMENTALS, symbol, as_of=as_of, end=event_date)
    if frame.empty:
        return {"status": "UNKNOWN", "reason": "fundamentals_dataset_missing"}
    frame = frame.sort_values("event_date").drop_duplicates("event_date", keep="last")
    if len(frame) < 4:
        return {"status": "UNKNOWN", "reason": "fewer_than_four_pit_periods", "periods": int(len(frame))}
    accepted = frame["quality_flags"].map(
        lambda value: isinstance(value, dict) and value.get("accepted_at") not in (None, "missing", "")
    )
    if not bool(accepted.all()):
        return {
            "status": "UNKNOWN",
            "reason": "accepted_at_missing_for_historical_period",
            "periods": int(len(frame)),
            "accepted_periods": int(accepted.sum()),
        }
    latest = frame.iloc[-1]
    required = ("revenue", "gross_profit", "operating_cash_flow", "total_debt", "cash")
    if any(_numeric(latest.get(column)) is None for column in required):
        return {"status": "UNKNOWN", "reason": "required_fundamental_field_missing", "periods": int(len(frame))}
    revenue = float(latest["revenue"])
    margin = float(latest["gross_profit"]) / revenue if revenue > 0 else None
    ocf = float(latest["operating_cash_flow"])
    debt = float(latest["total_debt"])
    cash = float(latest["cash"])
    if revenue <= 0 or margin is None or margin < 0.15 or ocf <= 0 or debt - cash > 5.0 * ocf:
        return {"status": "FAIL", "reason": "quality_rule_failed", "periods": int(len(frame)),
                "gross_margin": round(margin, 8) if margin is not None else None}
    if symbol.upper() in {"SNDK", "MU", "WDC"}:
        return {"status": "UNKNOWN", "reason": "storage_cycle_fields_missing",
                "periods": int(len(frame)), "gross_margin": round(margin, 8)}
    return {
        "status": "PASS",
        "reason": "row_level_sec_acceptance_timestamp_and_quality_rule_passed",
        "pit_scope": "row_level_only_global_dataset_not_promotable",
        "periods": int(len(frame)),
        "gross_margin": round(margin, 8),
    }


def run() -> dict[str, Any]:
    manifest = pin(
        "deep_drawdown_rebound_v1",
        params={
            "model_revision": "deep-drawdown-quality-rebound-v1",
            "config": str(CONFIG_PATH),
            "drawdown_fraction": 0.50,
            "tranche_offsets": TRANCHE_OFFSETS,
            "horizons_days": HORIZONS,
            "cost_multiples": (1.0, 2.0, 3.0),
        },
    )
    all_events: list[dict[str, Any]] = []
    sleeve_reports: dict[str, Any] = {}
    for sleeve in SLEEVES:
        events: list[dict[str, Any]] = []
        coverage: list[dict[str, Any]] = []
        fundamental_coverage: list[dict[str, Any]] = []
        for symbol in sleeve.symbols:
            frame = store.read(store.DAILY_BARS, symbol, as_of=manifest.as_of)
            fundamental_frame = store.read(store.FUNDAMENTALS, symbol, as_of=manifest.as_of)
            coverage.append({
                "symbol": symbol,
                "rows": int(len(frame)),
                "start": str(frame["event_date"].min())[:10] if len(frame) else None,
                "end": str(frame["event_date"].max())[:10] if len(frame) else None,
                "source": sorted({str(v) for v in frame.get("source", []).dropna().tolist() if v is not None}),
                "price_basis": sorted({str(v) for v in frame.get("price_basis", []).dropna().tolist() if v is not None}),
                "missing_price_basis_rows": int(frame["price_basis"].isna().sum())
                if "price_basis" in frame else int(len(frame)),
            })
            fundamental_coverage.append({
                "symbol": symbol,
                "rows": int(len(fundamental_frame)),
                "start": str(fundamental_frame["event_date"].min())[:10] if len(fundamental_frame) else None,
                "end": str(fundamental_frame["event_date"].max())[:10] if len(fundamental_frame) else None,
                "source": sorted({str(v) for v in fundamental_frame.get("source", []).dropna().tolist() if v is not None}),
            })
            for event in _first_drawdown_events(frame):
                event = {"symbol": symbol, "domain": sleeve.key, **event}
                event["fundamental_quality"] = _fundamental_quality(symbol, event["event_date"], manifest.as_of)
                event["outcomes"] = _event_outcomes(frame, event, sleeve.cost_bps)
                events.append(event)
                all_events.append(event)
        horizon_reports: dict[str, Any] = {}
        for horizon in HORIZONS:
            def outcomes_for(selected_events):
                outcomes = []
                for event in selected_events:
                    item = next((o for o in event["outcomes"] if int(o["horizon_days"]) == horizon), None)
                    if item is not None:
                        outcomes.append({
                            "status": item["status"],
                            "gross_return": item["gross_return"],
                            "cost_bps": item["cost_bps"],
                        })
                return outcomes

            horizon_outcomes = outcomes_for(events)
            horizon_reports[str(horizon)] = {
                "diagnostic_all_events": _summary(horizon_outcomes, cost_multiple=1.0),
                "quality_pass_only": _summary(
                    outcomes_for([e for e in events if e["fundamental_quality"]["status"] == "PASS"]),
                    cost_multiple=1.0,
                ),
                "cost_stress": [_summary(horizon_outcomes, cost_multiple=m) for m in (1.0, 2.0, 3.0)],
                "split": _split(events),
            }
        sleeve_reports[sleeve.key] = {
            "symbols": list(sleeve.symbols),
            "cost_bps_round_trip": sleeve.cost_bps,
            "coverage": coverage,
            "fundamental_coverage": fundamental_coverage,
            "event_count": len(events),
            "events": events,
            "quality_pass_events": sum(e["fundamental_quality"]["status"] == "PASS" for e in events),
            "quality_unknown_events": sum(e["fundamental_quality"]["status"] == "UNKNOWN" for e in events),
            "quality_fail_events": sum(e["fundamental_quality"]["status"] == "FAIL" for e in events),
            "independent_asset_clusters": len({e["symbol"] for e in events}),
            "independent_date_clusters": len({e["event_date"] for e in events}),
            "horizons": horizon_reports,
        }
        manifest.record_input(
            f"daily_bars:{sleeve.key}",
            symbols=len(sleeve.symbols),
            events=len(events),
            coverage=coverage,
            strict_historical_pit=False,
        )
        manifest.record_input(
            f"fundamentals:{sleeve.key}",
            symbols=len(sleeve.symbols),
            rows=sum(item["rows"] for item in fundamental_coverage),
            coverage=fundamental_coverage,
            strict_historical_pit=False,
        )
    report = {
        "schema_version": "deep-drawdown-rebound-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "as_of": manifest.as_of.isoformat(),
        "real_data_only": True,
        "strategy_status": "UNKNOWN",
        "promotion_status": "UNKNOWN",
        "execution_basis": "diagnostic_next_open_to_close; no historical quote/depth tape",
        "pit_status": "UNKNOWN",
        "strict_historical_pit": False,
        "survivorship_control": "UNKNOWN",
        "fundamental_quality_filter": "ROW_LEVEL_CANDIDATE_GLOBAL_BLOCKED",
        "fundamental_quality_summary": {
            "pass_events": sum(e["fundamental_quality"]["status"] == "PASS" for e in all_events),
            "unknown_events": sum(e["fundamental_quality"]["status"] == "UNKNOWN" for e in all_events),
            "fail_events": sum(e["fundamental_quality"]["status"] == "FAIL" for e in all_events),
            "interpretation": "row-level acceptance and quality only; global PIT/survivorship/executable gates remain blocked",
        },
        "asset_date_cluster_floor": {
            "min_assets": MIN_ASSET_CLUSTERS,
            "min_dates": MIN_DATE_CLUSTERS,
            "status": "UNKNOWN",
        },
        "event_definition": "first close crossing >=50% below prior expanding close peak per asset episode",
        "all_event_count": len(all_events),
        "sleeves": sleeve_reports,
        "limitations": [
            "daily bars are not strict historical PIT data",
            "diagnostic fills have no historical bid/ask/depth or partial-fill evidence",
            "asset/date two-way clustered inference is not yet implemented",
            "delisted/zero-liquidity history is not proven complete for every sleeve",
        ],
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    manifest.save(REPORT_PATH)
    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps({
        "status": result["strategy_status"],
        "all_event_count": result["all_event_count"],
        "sleeves": {k: v["event_count"] for k, v in result["sleeves"].items()},
        "report": str(REPORT_PATH),
    }, ensure_ascii=False))
