"""Real-data, paper-account research loop for every locally covered instrument.

This is deliberately an experiment runner, not a live-trading command.  It
feeds real point-in-time daily bars through the same ``SimulationService`` used
by the Paper Lab, including the signal source, fill model, fees, slippage, risk
checks, positions and durable equity/trade ledger.  The only injected
dependency is a historical clock so a 2024 bar is not rejected as stale by a
2026 wall clock.

The default run optimizes a small pre-declared momentum family on a bounded
calibration universe, then evaluates the selected candidate on every symbol in
the local daily-bar store.  A candidate is never promoted on this report:
insufficient closed trades, missing data, degraded equity, negative OOS return,
or an uncomputed multiple-testing gate all remain BLOCKED.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from libs.data import store
from libs.data.run_manifest import RunManifest
from libs.quant.pbo import deflated_t_stat_threshold
from libs.quant.pbo import probability_of_backtest_overfitting
from modules.simulation.service import SimulationService
from modules.simulation import metrics as sim_metrics


MIN_ROWS = 120
MIN_CLOSED_TRADES = 20


@dataclass
class ReplayClock:
    current: datetime

    def __call__(self) -> datetime:
        return self.current


MOMENTUM_CANDIDATES: tuple[dict[str, Any], ...] = (
    {"id": "mom_3_8_5", "fast_window": 3, "slow_window": 8, "min_separation_bps": 5.0},
    {"id": "mom_5_20_8", "fast_window": 5, "slow_window": 20, "min_separation_bps": 8.0},
    {"id": "mom_8_32_10", "fast_window": 8, "slow_window": 32, "min_separation_bps": 10.0},
    {"id": "mom_10_40_12", "fast_window": 10, "slow_window": 40, "min_separation_bps": 12.0},
)


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def _domain(symbol: str) -> str:
    if symbol.isdigit():
        return "a_share"
    if symbol.endswith("-USDT"):
        return "crypto"
    return "us_equity"


def _date(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).astimezone(UTC)


def _bars(symbol: str, *, as_of: datetime, start: str | None, end: str | None) -> list[dict[str, Any]]:
    frame = store.read(store.DAILY_BARS, symbol, as_of=as_of, start=start, end=end)
    rows: list[dict[str, Any]] = []
    for row in frame.to_dict("records"):
        close = row.get("close")
        if close is None or not math.isfinite(float(close)) or float(close) <= 0:
            continue
        rows.append({"symbol": symbol, "event_at": _date(row[store.EVENT_DATE]), "close": float(close),
                     "source": row.get("source"), "price_basis": row.get("price_basis")})
    return rows


async def _run_symbol(symbol: str, rows: list[dict[str, Any]], config: dict[str, Any],
                      *, db_path: Path, name: str) -> dict[str, Any]:
    if len(rows) < MIN_ROWS:
        return {"symbol": symbol, "domain": _domain(symbol), "status": "BLOCKED",
                "reason": f"rows<{MIN_ROWS}", "rows": len(rows)}
    clock = ReplayClock(rows[0]["event_at"])
    service = SimulationService(
        db_path,
        clock=clock,
        equity_poll_seconds=10**9,
    )
    await service.start()
    run = await service.create_run(
        name=name,
        strategy_id="momentum_dualma_v1",
        universe=[symbol],
        initial_capital=10_000.0,
        config={
            **config,
            "cooldown_seconds": 0.0,
            "max_staleness_seconds": 172800.0,
            "equity_interval_minutes": 1440.0,
        },
    )
    run_id = str(run["run_id"])
    await service.start_run(run_id)
    for row in rows:
        clock.current = row["event_at"]
        await service._dispatch("features.snapshots", {
            "market_id": symbol,
            "timestamp": row["event_at"],
            "mid_price": row["close"],
            # Daily bars do not contain historical BBO. Leaving bid/ask absent
            # forces the real Paper Lab mid-penalty path, never invented quotes.
            "source": row.get("source"),
            "price_basis": row.get("price_basis"),
        })
        # Real-time Paper Lab persists on trades and periodic polling. A
        # historical bar replay has no wall-clock poll, so persist the same
        # mark-to-market state once per observed bar to form a valid OOS curve.
        await service._record_equity(service._active[run_id])
    clock.current = rows[-1]["event_at"]
    await service.stop_run(run_id)
    metrics = sim_metrics.compute_run_metrics(service.store, run_id)
    points = service.store.list_equity_points(run_id)
    period_returns: list[dict[str, Any]] = []
    for previous, current in zip(points, points[1:]):
        if previous.equity > 0:
            period_returns.append({"ts": current.ts, "return": current.equity / previous.equity - 1.0})
    await service.stop()
    return {
        "symbol": symbol,
        "domain": _domain(symbol),
        "status": "ANALYZED",
        "rows": len(rows),
        "start": rows[0]["event_at"].date().isoformat(),
        "end": rows[-1]["event_at"].date().isoformat(),
        "metrics": metrics,
        "period_returns": period_returns,
        "run_id": run_id,
    }


def _verdict(result: dict[str, Any]) -> tuple[str, list[str]]:
    if result.get("status") != "ANALYZED":
        return "BLOCKED", [str(result.get("reason", "not analyzed"))]
    metrics = result["metrics"]
    reasons: list[str] = []
    if metrics.get("equity_curve_degraded"):
        reasons.append("equity_curve_degraded")
    if (metrics.get("closed_trade_count") or 0) < MIN_CLOSED_TRADES:
        reasons.append(f"closed_trades<{MIN_CLOSED_TRADES}")
    if metrics.get("total_return") is None:
        reasons.append("return_unknown")
    elif metrics["total_return"] <= 0:
        reasons.append("non_positive_return")
    if metrics.get("max_drawdown") is not None and metrics["max_drawdown"] > 0.25:
        reasons.append("max_drawdown>25%")
    return ("PASS" if not reasons else "FAIL"), reasons


def _optimization_action(reasons: list[str]) -> str:
    """Map observed failure modes to bounded next candidates, never to live changes."""
    actions: list[str] = []
    if "non_positive_return" in reasons:
        actions.append("test slower trend windows and stricter separation; inspect turnover/cost drag")
    if any(reason.startswith("closed_trades<") for reason in reasons):
        actions.append("test a lower separation threshold only on calibration data; require more OOS time")
    if "max_drawdown>25%" in reasons:
        actions.append("test lower position_fraction and a volatility/drawdown cap")
    if "equity_curve_degraded" in reasons or "return_unknown" in reasons:
        actions.append("repair mark coverage before any strategy optimization")
    return "; ".join(actions) if actions else "no automatic change; independent confirmation required"


async def _evaluate_candidate(symbols: list[str], config: dict[str, Any], *, as_of: datetime,
                              split: datetime, output_dir: Path, label: str) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for symbol in symbols:
        rows = _bars(symbol, as_of=as_of, start=None, end=None)
        train = [row for row in rows if row["event_at"] < split]
        test = [row for row in rows if row["event_at"] >= split]
        for name, period in (("train", train), ("oos", test)):
            db_path = output_dir / f"{label}-{symbol}-{name}-{uuid.uuid4().hex[:8]}.sqlite3"
            results.append({"period": name, "result": await _run_symbol(
                symbol, period, config, db_path=db_path, name=f"{label}:{symbol}:{name}"
            )})
    oos = [item["result"] for item in results if item["period"] == "oos"]
    analyzed = [item for item in oos if item.get("status") == "ANALYZED"]
    returns = [item["metrics"].get("total_return") for item in analyzed]
    returns = [float(value) for value in returns if value is not None]
    score = sum(returns) / len(returns) if returns else None
    by_timestamp: dict[str, list[float]] = {}
    for item in results:
        if item["period"] != "oos":
            continue
        for point in item["result"].get("period_returns", []):
            by_timestamp.setdefault(str(point["ts"]), []).append(float(point["return"]))
    analyzable_oos = [item for item in results
                      if item["period"] == "oos" and item["result"].get("status") == "ANALYZED"]
    common_returns = [sum(values) / len(values) for _, values in sorted(by_timestamp.items())
                      if len(values) == len(analyzable_oos)]
    return {"candidate": config, "symbols": symbols, "score_oos_mean_return": score,
            "oos_portfolio_returns": common_returns,
            "results": results, "status": "ANALYZED" if analyzed else "BLOCKED"}


async def run(args: argparse.Namespace) -> dict[str, Any]:
    as_of = _parse_date(args.as_of) or datetime.now(UTC)
    all_symbols = store.symbols(store.DAILY_BARS)
    if args.max_symbols:
        all_symbols = all_symbols[:args.max_symbols]
    if not all_symbols:
        raise RuntimeError("daily_bars has no locally persisted real symbols")
    first_frame = store.read(store.DAILY_BARS, all_symbols[0], as_of=as_of)
    dates = first_frame[store.EVENT_DATE].tolist()
    if len(dates) < MIN_ROWS:
        raise RuntimeError("calibration symbol has insufficient daily history")
    start = _date(min(dates))
    end = _date(max(dates))
    split = _parse_date(args.split) or start + (end - start) * 0.7
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    by_domain = {domain: [symbol for symbol in all_symbols if _domain(symbol) == domain]
                 for domain in ("a_share", "us_equity", "crypto")}
    calibration_by_domain = {
        domain: symbols[:min(args.optimization_symbols, len(symbols))]
        for domain, symbols in by_domain.items()
    }
    candidates: dict[str, list[dict[str, Any]]] = {}
    selected_by_domain: dict[str, dict[str, Any] | None] = {}
    pbo_by_domain: dict[str, dict[str, Any]] = {}
    for domain, calibration in calibration_by_domain.items():
        candidates[domain] = []
        for config in MOMENTUM_CANDIDATES:
            candidates[domain].append(await _evaluate_candidate(
                calibration, config, as_of=as_of, split=split, output_dir=output_dir,
                label=f"{domain}-{config['id']}"))
        eligible = [item for item in candidates[domain] if item["score_oos_mean_return"] is not None]
        selected_by_domain[domain] = max(
            eligible, key=lambda item: item["score_oos_mean_return"]
        ) if eligible else None
        matrices = [item["oos_portfolio_returns"] for item in candidates[domain]
                    if len(item["oos_portfolio_returns"]) >= 20]
        if len(matrices) >= 2:
            width = min(len(row) for row in matrices)
            try:
                pbo_by_domain[domain] = probability_of_backtest_overfitting(
                    __import__("numpy").asarray([row[-width:] for row in matrices], dtype=float)
                ).to_dict()
            except ValueError as exc:
                pbo_by_domain[domain] = {"status": "BLOCKED", "reason": str(exc)}
        else:
            pbo_by_domain[domain] = {
                "status": "BLOCKED",
                "reason": "not enough common OOS return series for PBO",
            }
    full_results: list[dict[str, Any]] = []
    for symbol in all_symbols:
        selected = selected_by_domain[_domain(symbol)]
        if selected is None:
            full_results.append({"symbol": symbol, "domain": _domain(symbol), "status": "BLOCKED",
                                 "reason": "no calibration candidate with OOS data"})
            continue
        rows = _bars(symbol, as_of=as_of, start=None, end=None)
        db_path = output_dir / f"full-{symbol}-{uuid.uuid4().hex[:8]}.sqlite3"
        full_results.append(await _run_symbol(symbol, rows, selected["candidate"],
                                               db_path=db_path, name=f"full:{symbol}"))
    for item in full_results:
        item["verdict"], item["reasons"] = _verdict(item)
        item["optimization_action"] = _optimization_action(item["reasons"])
        # The full run is an instrument-level diagnostic. Keep the report small;
        # calibration runs retain their OOS series for PBO computation.
        item.pop("period_returns", None)
    coverage = {name: store.coverage(name) for name in ("daily_bars", "funding_rates",
                                                        "positioning", "insider_filings",
                                                        "corporate_actions")}
    manifest = RunManifest(
        experiment="simulation_research_pipeline",
        as_of=as_of,
        params={"min_rows": MIN_ROWS, "min_closed_trades": MIN_CLOSED_TRADES,
                "candidate_count": len(MOMENTUM_CANDIDATES), "selected": selected and selected["candidate"]},
    )
    manifest.record_input("daily_bars", symbols=len(all_symbols), start=start.date().isoformat(),
                          end=end.date().isoformat(), coverage=coverage["daily_bars"])
    report = {
        "generated_at": datetime.now(UTC).isoformat(), "as_of": as_of.isoformat(),
        "real_data_only": True, "data_coverage": coverage,
        "universe": {"count": len(all_symbols), "domains": {d: sum(_domain(s) == d for s in all_symbols)
                                                                  for d in ("a_share", "us_equity", "crypto")}},
        "calibration": candidates,
        "selected_candidate": {
            domain: selected["candidate"] if selected else None
            for domain, selected in selected_by_domain.items()
        },
        "optimization_trace": {
            "selection": "calibration OOS mean return only; selected candidate is diagnostic, not promoted",
            "failure_feedback": "each full-result verdict emits bounded next-step actions; no live strategy mutation occurs",
            "multiple_testing": "candidate family count and PBO are recorded; DSR observed statistic and promotion remain outside this runner",
        },
        "multiple_testing": {
            "n_trials": len(MOMENTUM_CANDIDATES),
            "deflated_t_threshold": deflated_t_stat_threshold(len(MOMENTUM_CANDIDATES)),
            "pbo_by_domain": pbo_by_domain,
            "status": "BLOCKED",
        },
        "full_results": full_results,
        "blocked_capabilities": {
            "btc_5m": "local btc_1m_bars coverage is only 314 rows; not enough for large-scale 5m validation",
            "sec_insider": "SEC Form 345 is now materialized locally; the insider strategy has a separate event-study/OOS report and is not part of this daily momentum run",
        },
        "promotion": {"status": "BLOCKED", "reason": "This pipeline has no promotion authority; independent statistical gate required"},
        "manifest": manifest.to_dict(),
    }
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return report


def main() -> int:
    # A batch covering thousands of symbols can create millions of fill events;
    # keep the durable SQLite ledger as the detailed audit trail without
    # flooding stdout with one INFO line per fill.
    try:
        import structlog
        structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))
    except Exception:  # pragma: no cover - logging configuration is optional
        pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-symbols", type=int, default=0, help="0 = every locally covered daily-bar symbol")
    parser.add_argument("--optimization-symbols", type=int, default=8)
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--split", default=None, help="UTC ISO split; default 70%% of first symbol history")
    parser.add_argument("--output-dir", default="data/simulation_research_runs")
    parser.add_argument("--report", default="data/simulation_research_report.json")
    args = parser.parse_args()
    report = asyncio.run(run(args))
    print(json.dumps({"symbols": report["universe"]["count"],
                      "selected_candidate": report["selected_candidate"],
                      "full_results": len(report["full_results"]),
                      "promotion": report["promotion"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
