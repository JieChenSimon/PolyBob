"""Replay the fixed cross-sectional momentum rule over multiple OOS cut dates."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from libs.data import store
from libs.data.universe import US_LIQUID
from scripts.cross_sectional_kernel_replay import replay_symbol
from scripts.cross_sectional_local_screen import align_frames, read_frames, select_long_only

SPLIT_FRACTIONS = (0.50, 0.60, 0.70, 0.80)
LOOKBACK = 60
TOP_FRAC = 0.30
REBALANCE_DAYS = 10


def fold_dates(index: list[str], fractions: tuple[float, ...] = SPLIT_FRACTIONS) -> list[str]:
    if len(index) < 300:
        raise ValueError("multi-fold replay requires at least 300 observations")
    cuts = [index[int(len(index) * fraction)] for fraction in fractions]
    if len(set(cuts)) != len(cuts) or cuts != sorted(cuts):
        raise ValueError("fold cut dates must be unique and chronological")
    return cuts


def buy_and_hold_return(series, split_date: str) -> float | None:
    prior = series[series.index < split_date]
    future = series[series.index >= split_date]
    if prior.empty or future.empty or float(prior.iloc[-1]) <= 0:
        return None
    return float(future.iloc[-1] / prior.iloc[-1] - 1.0)


async def run_fold(split_date: str, frames: dict, positions: np.ndarray,
                   matrix_index: list[str], out_dir: Path) -> dict:
    results = []
    for symbol, target in zip(frames, positions):
        series = frames[symbol]
        dates = list(series.index)
        valid_dates = [date for date in dates if date in matrix_index]
        aligned_target = target[[matrix_index.index(date) for date in valid_dates]]
        prices = series.loc[valid_dates].to_numpy(dtype=float)
        timestamps = [datetime.fromisoformat(date) for date in valid_dates]
        replay = await replay_symbol(
            symbol, timestamps, prices.tolist(), aligned_target.tolist(), split_date, out_dir,
        )
        replay["benchmark_oos_return"] = buy_and_hold_return(series.loc[valid_dates], split_date)
        replay["excess_oos_return"] = (
            replay["oos_return"] - replay["benchmark_oos_return"]
            if replay["oos_return"] is not None and replay["benchmark_oos_return"] is not None
            else None
        )
        results.append(replay)

    def values(key: str) -> list[float]:
        return [float(row[key]) for row in results if row.get(key) is not None]

    oos = values("oos_return")
    excess = values("excess_oos_return")
    dd = [float(row["metrics"]["max_drawdown"]) for row in results
          if row.get("metrics", {}).get("max_drawdown") is not None]
    return {
        "split_date": split_date,
        "symbols": len(results),
        "mean_oos_return": float(np.mean(oos)) if oos else None,
        "median_oos_return": float(np.median(oos)) if oos else None,
        "positive_oos_fraction": float(np.mean(np.asarray(oos) > 0)) if oos else None,
        "mean_excess_oos_return": float(np.mean(excess)) if excess else None,
        "median_excess_oos_return": float(np.median(excess)) if excess else None,
        "positive_excess_fraction": float(np.mean(np.asarray(excess) > 0)) if excess else None,
        "median_full_max_drawdown": float(np.median(dd)) if dd else None,
        "median_oos_closed_trades": float(np.median([
            row["oos_closed_trades"] for row in results
        ])) if results else None,
        "results": results,
    }


async def main_async() -> int:
    as_of = datetime.now(UTC)
    frames, rejected = read_frames(list(US_LIQUID), as_of)
    matrix_frame = align_frames(frames)
    if len(frames) < 4 or matrix_frame.shape[0] < 300:
        raise RuntimeError("insufficient clean US liquid data")
    symbols = list(frames)
    matrix = matrix_frame.to_numpy(dtype=float).T
    positions = select_long_only(
        matrix, lookback=LOOKBACK, top_frac=TOP_FRAC, rebalance_days=REBALANCE_DAYS,
    )
    splits = fold_dates(list(matrix_frame.index))
    out_dir = Path("data/.kernel_replay_cross_sectional_multifold")
    out_dir.mkdir(parents=True, exist_ok=True)
    folds = [await run_fold(split, frames, positions, list(matrix_frame.index), out_dir)
             for split in splits]
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "real_data_only": True,
        "execution_kernel": "modules.simulation.SimulationService",
        "strategy": {"lookback": LOOKBACK, "top_frac": TOP_FRAC,
                      "rebalance_days": REBALANCE_DAYS, "long_only": True},
        "execution_config": {"fee_bps": 20.0, "mid_penalty_bps": 10.0, "allow_short": False},
        "universe": "US_LIQUID",
        "symbols": symbols,
        "quality_rejected": rejected,
        "split_fractions": list(SPLIT_FRACTIONS),
        "folds": folds,
        "status": "replay_only_not_promoted",
    }
    out = Path("data/cross_sectional_multifold_replay.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    print(json.dumps([{key: fold[key] for key in fold if key != "results"}
                      for fold in folds], ensure_ascii=False, indent=2))
    print(f"写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
