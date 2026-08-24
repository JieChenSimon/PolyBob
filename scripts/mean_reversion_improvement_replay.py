"""Replay constrained mean-reversion variants on real US data and the paper kernel."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from libs.data import store
from libs.data.universe import US_LIQUID
from libs.quant.promotion import PromotionGate, annualized_sharpe
from scripts.cross_sectional_kernel_replay import replay_symbol
from scripts.cross_sectional_local_screen import align_frames, read_frames

SPLITS = (0.50, 0.60, 0.70, 0.80)
CANDIDATES = (
    {"name": "symmetric_100", "lookback": 20, "entry_bps": 100, "exit_bps": 50,
     "position_fraction": 0.50, "allow_short": True},
    {"name": "symmetric_200", "lookback": 40, "entry_bps": 200, "exit_bps": 100,
     "position_fraction": 0.50, "allow_short": True},
)
COSTS = (1.0, 2.0, 3.0)


def symmetric_positions(prices: list[float], lookback: int, entry_bps: int,
                         exit_bps: int) -> np.ndarray:
    values = np.asarray(prices, dtype=float)
    positions = np.zeros(len(values), dtype=float)
    active = 0.0
    for i in range(lookback, len(values)):
        mean = float(np.mean(values[i - lookback:i]))
        if not np.isfinite(mean) or mean <= 0:
            continue
        deviation = (values[i] / mean - 1.0) * 10_000.0
        if deviation <= -entry_bps:
            active = 1.0
        elif deviation >= entry_bps:
            active = -1.0
        elif abs(deviation) <= exit_bps:
            active = 0.0
        positions[i] = active
    return positions


async def run_variant(candidate: dict, frames: dict, split: str, out_dir: Path,
                      cost_multiple: float = 1.0) -> dict:
    rows = []
    for symbol, series in frames.items():
        prices = series.to_numpy(dtype=float).tolist()
        positions = symmetric_positions(prices, candidate["lookback"], candidate["entry_bps"], candidate["exit_bps"])
        timestamps = [datetime.fromisoformat(date).replace(tzinfo=UTC) for date in series.index]
        row = await replay_symbol(
            symbol, timestamps, prices, positions.tolist(), split, out_dir,
            position_fraction=candidate["position_fraction"],
            allow_short=candidate["allow_short"], fee_bps=20.0 * cost_multiple,
            mid_penalty_bps=10.0 * cost_multiple,
        )
        rows.append(row)
    oos = [float(row["oos_return"]) for row in rows if row.get("oos_return") is not None]
    return {
        "candidate": candidate["name"], "cost_multiple": cost_multiple, "split_date": split,
        "symbols": len(rows), "mean_oos_return": float(np.mean(oos)) if oos else None,
        "median_oos_return": float(np.median(oos)) if oos else None,
        "positive_oos_fraction": float(np.mean(np.asarray(oos) > 0)) if oos else None,
        "median_max_drawdown": float(np.median([r["metrics"]["max_drawdown"] for r in rows])) if rows else None,
        "median_closed_trades": float(np.median([r["oos_closed_trades"] for r in rows])) if rows else None,
    }


async def main_async() -> int:
    frames, rejected = read_frames(list(US_LIQUID), datetime.now(UTC))
    matrix = align_frames(frames)
    if len(frames) < 20 or len(matrix) < 300:
        raise RuntimeError("insufficient clean US data")
    splits = [str(matrix.index[int(len(matrix) * fraction)]) for fraction in SPLITS]
    out_dir = Path("data/.kernel_replay_mean_reversion_improvement")
    out_dir.mkdir(parents=True, exist_ok=True)
    folds = []
    for candidate in CANDIDATES:
        for split in splits:
            costs = [await run_variant(candidate, frames, split, out_dir, multiple) for multiple in COSTS]
            base = costs[0]
            folds.append({"candidate": candidate["name"], "split_date": split, "costs": costs,
                          "base": base})
    by_candidate = {}
    for candidate in CANDIDATES:
        name = candidate["name"]
        selected = [f for f in folds if f["candidate"] == name]
        base_returns = [f["base"]["mean_oos_return"] for f in selected if f["base"]["mean_oos_return"] is not None]
        stability = float(np.mean(np.asarray(base_returns) > 0)) if base_returns else 0.0
        # Portfolio observations are approximated by fold means only for the gate;
        # symbol-level kernel runs remain the primary evidence above.
        gate = PromotionGate(n_trials=len(CANDIDATES) * len(COSTS), min_dsr=.90,
                             min_observations=200, min_oos_stability_rate=.5,
                             cost_min_sharpe=.3).evaluate(
            base_returns, cost_returns_fn=lambda multiple: [
                f["costs"][COSTS.index(multiple)]["mean_oos_return"] for f in selected
            ], cost_multiples=COSTS, oos_stability_rate=stability,
        )
        by_candidate[name] = {"folds": selected, "promotion": gate.to_dict()}
    report = {"generated_at": datetime.now(UTC).isoformat(), "real_data_only": True,
              "execution_kernel": "modules.simulation.SimulationService",
              "universe": "US_LIQUID", "symbols": len(frames), "quality_rejected": rejected,
              "candidates": [c for c in CANDIDATES], "cost_multiples": list(COSTS),
              "results": by_candidate, "status": "replay_only_not_promoted"}
    out = Path("data/mean_reversion_improvement_replay.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    print(json.dumps({name: value["promotion"] for name, value in by_candidate.items()}, ensure_ascii=False, indent=2))
    print(f"写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
