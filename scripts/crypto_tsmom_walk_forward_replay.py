"""Walk-forward crypto momentum replay with train-only candidate selection.

Each fold selects one domain-level candidate from a small pre-registered grid
using only data before the fold cut, then replays every instrument through the
real SimulationService kernel. OOS observations never influence selection.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import structlog

from libs.data import store
from scripts.cross_sectional_kernel_replay import replay_symbol
from scripts.cross_sectional_local_screen import align_frames, read_frames, symbol_domain
from scripts.mean_reversion_multifold_replay import buy_and_hold_return, fold_dates
from strategies.proven_signals import time_series_momentum


CANDIDATES = tuple(
    {"lookback": lookback, "vol_lookback": vol_lookback, "threshold": threshold}
    for lookback in (60, 120)
    for vol_lookback in (20, 40)
    for threshold in (0.15, 0.25)
)
POSITION_FRACTION = 0.50
FEE_BPS = 20.0
EVENT_SLEEP_SECONDS = 0.005
EQUITY_SAMPLE_EVERY = 5


def candidate_positions(prices: np.ndarray, candidate: dict[str, float]) -> np.ndarray:
    signal = np.asarray(time_series_momentum(
        prices,
        lookback=int(candidate["lookback"]),
        vol_lookback=int(candidate["vol_lookback"]),
    ), dtype=float)
    threshold = float(candidate["threshold"])
    return np.where(signal >= threshold, 1.0,
                    np.where(signal <= -threshold, -1.0, 0.0))


def train_score(series, split_date: str, candidate: dict[str, float]) -> float | None:
    prices = series.to_numpy(dtype=float)
    cut = int(np.searchsorted(np.asarray(series.index), split_date, side="left"))
    if cut < int(candidate["lookback"]) + 30:
        return None
    positions = candidate_positions(prices, candidate)
    returns = prices[1:] / prices[:-1] - 1.0
    active = positions[:-1]
    previous = np.concatenate([[0.0], active[:-1]])
    net = active * returns - np.abs(active - previous) * FEE_BPS / 10_000.0
    train = net[int(candidate["lookback"]):cut - 1]
    if len(train) < 30 or not np.all(np.isfinite(train)):
        return None
    volatility = float(np.std(train, ddof=1))
    if volatility <= 0:
        return float(np.mean(train))
    return float(np.mean(train) / volatility * np.sqrt(365.0))


def select_candidate(frames: dict, split_date: str) -> tuple[dict[str, float], list[dict]]:
    scores = []
    for candidate in CANDIDATES:
        values = [score for series in frames.values()
                  if (score := train_score(series, split_date, candidate)) is not None]
        scores.append({
            "candidate": candidate,
            "symbols_scored": len(values),
            "mean_train_sharpe": float(np.mean(values)) if values else None,
            "median_train_sharpe": float(np.median(values)) if values else None,
        })
    usable = [row for row in scores if row["mean_train_sharpe"] is not None]
    if not usable:
        raise RuntimeError(f"no train candidate available before {split_date}")
    chosen = max(usable, key=lambda row: (
        float(row["median_train_sharpe"]), float(row["mean_train_sharpe"])))
    return dict(chosen["candidate"]), scores


async def run_fold(split_date: str, frames: dict, out_dir: Path) -> dict:
    candidate, selection = select_candidate(frames, split_date)
    results = []
    for symbol, series in frames.items():
        prices = series.to_numpy(dtype=float)
        positions = candidate_positions(prices, candidate)
        oos_start = int(np.searchsorted(np.asarray(series.index), split_date, side="left"))
        # The candidate and signal path are computed causally from the full
        # history, but only fresh OOS bars enter the execution kernel. This
        # prevents training-period fills/PnL from contaminating OOS capital.
        oos_prices = prices[oos_start:]
        oos_positions = positions[oos_start:]
        oos_dates = list(series.index[oos_start:])
        timestamps = [datetime.fromisoformat(date) for date in oos_dates]
        replay = await replay_symbol(
            symbol, timestamps, oos_prices.tolist(), oos_positions.tolist(), split_date, out_dir,
            position_fraction=POSITION_FRACTION, allow_short=True, fee_bps=FEE_BPS,
            event_sleep_seconds=EVENT_SLEEP_SECONDS,
            equity_sample_every=EQUITY_SAMPLE_EVERY,
        )
        benchmark = buy_and_hold_return(series, split_date)
        replay["benchmark_oos_return"] = benchmark
        replay["excess_oos_return"] = (
            replay["oos_return"] - benchmark
            if replay.get("oos_return") is not None and benchmark is not None else None
        )
        results.append(replay)
    oos = [float(row["oos_return"]) for row in results if row.get("oos_return") is not None]
    excess = [float(row["excess_oos_return"]) for row in results
              if row.get("excess_oos_return") is not None]
    return {
        "split_date": split_date,
        "selected_candidate": candidate,
        "candidate_family_size": len(CANDIDATES),
        "selection_uses_oos": False,
        "train_selection": selection,
        "symbols": len(results),
        "mean_oos_return": float(np.mean(oos)) if oos else None,
        "median_oos_return": float(np.median(oos)) if oos else None,
        "positive_oos_fraction": float(np.mean(np.asarray(oos) > 0)) if oos else None,
        "mean_excess_oos_return": float(np.mean(excess)) if excess else None,
        "median_excess_oos_return": float(np.median(excess)) if excess else None,
        "results": results,
    }


async def main_async(major_only: bool, output: str, latest_only: bool = False) -> int:
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING)
    )
    as_of = datetime.now(UTC)
    major = {
        "BTC-USDT", "ETH-USDT", "BNB-USDT", "SOL-USDT", "XRP-USDT", "ADA-USDT",
        "DOGE-USDT", "TRX-USDT", "AVAX-USDT", "LINK-USDT", "DOT-USDT", "LTC-USDT",
        "BCH-USDT", "UNI-USDT", "ATOM-USDT", "NEAR-USDT", "ETC-USDT", "FIL-USDT",
    }
    symbols = [symbol for symbol in store.symbols(store.DAILY_BARS)
               if symbol_domain(symbol) == "crypto" and (not major_only or symbol in major)]
    frames, rejected = read_frames(symbols, as_of)
    matrix = align_frames(frames)
    if len(frames) < 4 or matrix.shape[0] < 300:
        raise RuntimeError("insufficient clean crypto data")
    splits = fold_dates(list(matrix.index))
    out_dir = Path("data/.kernel_replay_crypto_tsmom_walk_forward")
    out_dir.mkdir(parents=True, exist_ok=True)
    selected_splits = splits[-1:] if latest_only else splits
    folds = [await run_fold(split, frames, out_dir) for split in selected_splits]
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "real_data_only": True,
        "execution_kernel": "modules.simulation.SimulationService",
        "candidate_grid": list(CANDIDATES),
        "execution_config": {"fee_bps": FEE_BPS, "position_fraction": POSITION_FRACTION,
                              "allow_short": True, "equity_sample_every": EQUITY_SAMPLE_EVERY,
                              "event_sleep_seconds": EVENT_SLEEP_SECONDS},
        "symbols": len(frames), "quality_rejected": rejected,
        "folds": folds, "selection_is_train_only": True,
        "oos_execution_capital": "fresh_initial_capital_per_symbol_and_fold",
        "latest_fold_only": latest_only,
        "status": "replay_only_not_promoted",
    }
    Path(output).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    print(json.dumps([{key: fold[key] for key in (
        "split_date", "selected_candidate", "mean_oos_return", "median_oos_return",
        "mean_excess_oos_return", "positive_oos_fraction",
    )} for fold in folds], ensure_ascii=False, indent=2))
    print(f"写入 {output}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--major-only", action="store_true")
    parser.add_argument("--latest-fold-only", action="store_true")
    parser.add_argument("--output", default="data/crypto_tsmom_walk_forward_replay.json")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main_async(args.major_only, args.output, args.latest_fold_only)))
