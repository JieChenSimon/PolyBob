"""Bounded, real-data optimization of the SEC insider-cluster hypothesis.

This runner is intentionally separate from the pre-registered headline study:
it may propose a better-defined candidate, but it cannot promote one. Candidate
selection uses only 2024-2025 filing events; 2026 is a frozen OOS period. The
alpha comparison uses unscaled event returns so volatility sizing cannot hide a
bad signal. A conservative risk-scaled diagnostic is reported separately.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from libs.data import store
from libs.data.sec_insider import cluster_buys, fetch_insider_trades
from libs.data.run_manifest import RunManifest
from libs.quant.edge_backtest import replay_events
from libs.quant.edge import Direction
from libs.quant.pbo import deflated_t_stat_threshold

QUARTERS = [
    (year, quarter)
    for year in (2024, 2025, 2026)
    for quarter in (1, 2, 3, 4)
    if (year, quarter) <= (2026, 2)
]
TRAIN_END = "2025-12-31"
OOS_START = "2026-01-01"
COST_BPS = 10.0
HOLD_DAYS = (5, 10, 20)
MIN_INSIDERS = (2, 3)
MIN_VALUE_USD = (25_000.0, 50_000.0, 100_000.0)


def _score(result: dict) -> dict:
    # BacktestResult.to_dict() flattens inference fields at the top level and
    # keeps ``inference`` as the method label.
    inference = result
    return {
        "n": inference.get("n", 0),
        "mean_excess_pct": inference.get("mean_excess_pct"),
        "median_excess_pct": inference.get("median_excess_pct"),
        "win_rate": inference.get("win_rate"),
        "t_clustered": inference.get("t_stat"),
        "bootstrap_ci_pct": inference.get("bootstrap_ci_pct"),
        "wild_p": inference.get("wild_p"),
        "evidence_status": inference.get("status", "unknown"),
        "cluster_by": inference.get("cluster_by"),
        "dropped": result.get("dropped", {}),
    }


def _events(trades, min_insiders: int, min_value: float) -> list[tuple[str, str]]:
    clusters = cluster_buys(trades, min_insiders=min_insiders, min_value_usd=min_value)
    return sorted(clusters)


def main() -> int:
    all_trades = []
    for year, quarter in QUARTERS:
        all_trades.extend(fetch_insider_trades(year, quarter))

    # Use only locally persisted real prices. Missing price coverage is a visible
    # blocker; this optimizer does not silently fetch a different universe.
    symbols = store.symbols(store.DAILY_BARS)
    as_of = datetime.now(UTC)
    price_frame = store.read(store.DAILY_BARS, symbols, as_of=as_of)
    price_symbols = sorted(set(str(s) for s in price_frame["symbol"].tolist()))

    candidates: list[dict] = []
    for hold in HOLD_DAYS:
        for min_insiders in MIN_INSIDERS:
            for min_value in MIN_VALUE_USD:
                events = _events(all_trades, min_insiders, min_value)
                train = [event for event in events if event[1] <= TRAIN_END]
                oos = [event for event in events if event[1] >= OOS_START]
                common = {
                    "direction": Direction.LONG,
                    "hold_sessions": hold,
                    "benchmark": None,
                    "cost_bps": COST_BPS,
                    "as_of": as_of,
                    "t_hurdle": deflated_t_stat_threshold(18),
                    "edge_id": f"insider_cluster_{hold}_{min_insiders}_{int(min_value)}",
                    "neutralise_universe": price_symbols,
                    "risk_scale_window": None,
                    "bootstrap_draws": 499,
                    "wild_draws": 199,
                }
                train_result = replay_events(train, **common)
                oos_result = replay_events(oos, **common)
                candidates.append({
                    "params": {"hold_sessions": hold, "min_insiders": min_insiders,
                               "min_value_usd": min_value},
                    "events": {"all": len(events), "train": len(train), "oos": len(oos)},
                    "train": _score(train_result.to_dict()),
                    "oos": _score(oos_result.to_dict()),
                })

    eligible = [c for c in candidates
                if c["train"]["mean_excess_pct"] is not None and c["train"]["n"] >= 100]
    selected = max(eligible, key=lambda c: c["train"]["mean_excess_pct"]) if eligible else None
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "real_data_only": True,
        "selection_rule": "maximise train mean excess after costs; no OOS selection",
        "train_end": TRAIN_END,
        "oos_start": OOS_START,
        "candidate_count": len(candidates),
        "data": {"sec_quarters": QUARTERS, "daily_price_symbols": len(price_symbols),
                 "coverage_note": "events without local prices remain dropped/visible"},
        "selected_candidate": selected,
        "candidates": candidates,
        "promotion": {"status": "BLOCKED",
                       "reason": "optimizer proposes candidates; independent promotion gate remains required"},
    }
    manifest = RunManifest(
        experiment="insider_strategy_optimization",
        as_of=as_of,
        params={"candidate_count": len(candidates), "train_end": TRAIN_END,
                "oos_start": OOS_START, "cost_bps": COST_BPS},
    )
    manifest.record_input("insider_filings", quarters=QUARTERS, trades=len(all_trades))
    manifest.record_input("daily_bars", symbols=len(price_symbols), as_of=as_of.isoformat())
    out = Path("data/insider_optimization_results.json")
    out.write_text(json.dumps({**report, "manifest": manifest.to_dict()},
                              ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"selected": selected, "candidate_count": len(candidates),
                      "promotion": report["promotion"]}, ensure_ascii=False, indent=2))
    print(f"写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
