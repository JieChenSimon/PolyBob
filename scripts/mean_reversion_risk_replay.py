"""Stress mean-reversion exposure size through the real Paper Lab kernel."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from libs.data import store
from libs.data.universe import US_LIQUID
from scripts.cross_sectional_kernel_replay import replay_symbol
from scripts.cross_sectional_local_screen import align_frames, read_frames
from scripts.mean_reversion_research import mean_reversion_positions

FRACTIONS = (1.0, 0.5, 0.25, 0.10)


async def run_fraction(fraction: float, frames: dict, split_date: str, out_dir: Path) -> dict:
    results = []
    for symbol, series in frames.items():
        prices = series.to_numpy(dtype=float)
        positions = mean_reversion_positions(prices, lookback=20, entry_bps=100)
        timestamps = [datetime.fromisoformat(date) for date in series.index]
        results.append(await replay_symbol(
            symbol, timestamps, prices.tolist(), positions.tolist(), split_date, out_dir,
            position_fraction=fraction,
        ))
    returns = [float(item["oos_return"]) for item in results if item.get("oos_return") is not None]
    drawdowns = [item["metrics"].get("max_drawdown") for item in results
                 if item["metrics"].get("max_drawdown") is not None]
    return {
        "position_fraction": fraction, "symbols": len(results),
        "mean_oos_return": float(np.mean(returns)) if returns else None,
        "median_oos_return": float(np.median(returns)) if returns else None,
        "positive_oos_fraction": float(np.mean(np.asarray(returns) > 0)) if returns else None,
        "median_full_max_drawdown": float(np.median(drawdowns)) if drawdowns else None,
        "max_full_max_drawdown": float(np.max(drawdowns)) if drawdowns else None,
        "median_oos_closed_trades": float(np.median([item["oos_closed_trades"] for item in results])) if results else None,
        "results": results,
    }


async def main_async() -> int:
    as_of = datetime.now(UTC)
    frames, rejected = read_frames(list(US_LIQUID), as_of)
    matrix = align_frames(frames)
    if len(frames) < 4 or matrix.shape[0] < 300:
        raise RuntimeError("insufficient clean US liquid data")
    split_date = str(matrix.index[int(matrix.shape[0] * 0.7)])
    out_dir = Path("data/.kernel_replay_mean_reversion_risk")
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [await run_fraction(fraction, frames, split_date, out_dir) for fraction in FRACTIONS]
    report = {
        "generated_at": datetime.now(UTC).isoformat(), "real_data_only": True,
        "execution_kernel": "modules.simulation.SimulationService",
        "strategy": {"lookback": 20, "entry_bps": 100, "long_only": True},
        "execution_config": {"fee_bps": 20.0, "mid_penalty_bps": 10.0, "allow_short": False},
        "split_date": split_date, "symbols": len(frames), "quality_rejected": rejected,
        "rows": rows, "status": "replay_only_not_promoted",
    }
    out = Path("data/mean_reversion_risk_replay.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    print(json.dumps([{k: row[k] for k in row if k != "results"} for row in rows], ensure_ascii=False, indent=2))
    print(f"写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
