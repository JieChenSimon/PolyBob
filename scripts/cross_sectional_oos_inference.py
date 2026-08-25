"""Cluster-robust, multiple-testing-aware inference for one OOS screen candidate."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from libs.data import store
from libs.quant.clustered_inference import analyse
from libs.quant.pbo import deflated_t_stat_threshold
from scripts.cross_sectional_local_screen import (
    COST_BPS,
    align_frames,
    apply_risk_policy,
    read_frames,
    select_long_only,
    symbol_domain,
    symbols_from_discovery_manifest,
)
from scripts.multi_asset_portfolio_replay import stable_daily_frames


def daily_oos_excess(
    matrix: np.ndarray, positions: np.ndarray, dates: list[str], *,
    cut: int, cost_bps: float,
) -> tuple[list[float], list[str]]:
    """Return daily net strategy minus equal-weight benchmark returns."""
    net: list[float] = []
    excess_dates: list[str] = []
    previous = np.zeros(matrix.shape[0], dtype=float)
    for day in range(cut, matrix.shape[1] - 1):
        current = positions[:, day]
        valid = (
            (current > 0)
            & np.isfinite(matrix[:, day])
            & np.isfinite(matrix[:, day + 1])
            & (matrix[:, day] > 0)
        )
        benchmark_valid = (
            np.isfinite(matrix[:, day])
            & np.isfinite(matrix[:, day + 1])
            & (matrix[:, day] > 0)
        )
        if not valid.any() or not benchmark_valid.any():
            continue
        weights = current[valid]
        weights = weights / weights.sum()
        asset_returns = matrix[valid, day + 1] / matrix[valid, day] - 1.0
        strategy = float(np.dot(weights, asset_returns))
        turnover = float(np.abs(current - previous).sum())
        strategy -= turnover * cost_bps / 10_000.0
        benchmark_returns = matrix[benchmark_valid, day + 1] / matrix[benchmark_valid, day] - 1.0
        benchmark = float(np.mean(benchmark_returns))
        net.append(strategy - benchmark)
        excess_dates.append(str(dates[day + 1])[:10])
        previous = current
    return net, excess_dates


def run(args: argparse.Namespace) -> dict[str, Any]:
    requested = symbols_from_discovery_manifest(args.discovery_manifest)
    symbols = [symbol for symbol in requested if symbol_domain(symbol) == args.domain]
    frames, rejected_quality = read_frames(symbols, datetime.now(UTC))
    frames, rejected_stale = stable_daily_frames(
        frames, max_gap_days=14 if args.domain == "a_share" else 4,
    )
    aligned = align_frames(frames)
    matrix = aligned.to_numpy(dtype=float).T
    if matrix.shape[0] < 4 or matrix.shape[1] < 300:
        raise RuntimeError("insufficient stable data for OOS inference")
    cut = int(matrix.shape[1] * 0.7)
    candidate = {
        "lookback": args.lookback,
        "top_frac": args.top_frac,
        "rebalance_days": args.rebalance_days,
        "risk_policy": args.risk_policy,
    }
    positions = apply_risk_policy(
        matrix,
        select_long_only(matrix, args.lookback, args.top_frac, args.rebalance_days),
        args.risk_policy,
    )
    returns, dates = daily_oos_excess(
        matrix, positions, [str(value) for value in aligned.index],
        cut=cut, cost_bps=COST_BPS[args.domain],
    )
    n_trials = args.n_trials
    inference = analyse(
        returns, dates,
        t_hurdle=deflated_t_stat_threshold(n_trials),
        hold_days=args.rebalance_days,
        cluster_by="month",
        bootstrap_draws=args.bootstrap_draws,
        wild_draws=args.wild_draws,
        seed=args.seed,
        min_clusters=20,
    ).to_dict()
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "real_data_only": True,
        "research_only": True,
        "domain": args.domain,
        "symbols": sorted(frames),
        "rejected_quality": rejected_quality,
        "rejected_stale": rejected_stale,
        "oos_window": {"start": dates[0] if dates else None, "end": dates[-1] if dates else None,
                        "observations": len(returns), "cut_row": cut},
        "candidate": candidate,
        "n_trials": n_trials,
        "cost_bps": COST_BPS[args.domain],
        "inference": inference,
        "promotion": "BLOCKED" if inference.get("status") != "pass" else "RESEARCH_ONLY",
        "promotion_reason": "cluster_floor_or_multiple_testing_or_execution_gate_not_passed",
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", choices=("a_share", "us_equity"), required=True)
    parser.add_argument("--discovery-manifest", default="data/discovered_equity_universe_full.json")
    parser.add_argument("--lookback", type=int, default=60)
    parser.add_argument("--top-frac", type=float, default=0.2)
    parser.add_argument("--rebalance-days", type=int, default=10)
    parser.add_argument("--risk-policy", choices=("raw", "vol_target_10", "vol_target_10_dd"), default="vol_target_10")
    parser.add_argument("--n-trials", type=int, default=54)
    parser.add_argument("--bootstrap-draws", type=int, default=2000)
    parser.add_argument("--wild-draws", type=int, default=1999)
    parser.add_argument("--seed", type=int, default=20260825)
    parser.add_argument("--output", default="/tmp/polybob_cross_sectional_oos_inference.json")
    args = parser.parse_args()
    report = run(args)
    print(json.dumps({"output": args.output, "status": report["inference"]["status"],
                      "n_clusters": report["inference"]["n_clusters"],
                      "t_stat": report["inference"]["t_stat"],
                      "t_hurdle": report["inference"]["t_hurdle"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
