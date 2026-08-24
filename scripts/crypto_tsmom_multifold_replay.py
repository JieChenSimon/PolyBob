"""Replay a signed crypto time-series momentum candidate through Paper Lab."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from libs.data import store
from scripts.cross_sectional_kernel_replay import replay_symbol
from scripts.cross_sectional_local_screen import align_frames, read_frames, symbol_domain
from scripts.mean_reversion_multifold_replay import buy_and_hold_return, fold_dates
from strategies.proven_signals import time_series_momentum

LOOKBACK = 120
VOL_LOOKBACK = 20
THRESHOLD = 0.25
POSITION_FRACTION = 0.50
MAJOR_CRYPTO = frozenset({
    "BTC-USDT", "ETH-USDT", "BNB-USDT", "SOL-USDT", "XRP-USDT", "ADA-USDT",
    "DOGE-USDT", "TRX-USDT", "AVAX-USDT", "LINK-USDT", "DOT-USDT", "LTC-USDT",
    "BCH-USDT", "UNI-USDT", "ATOM-USDT", "NEAR-USDT", "ETC-USDT", "FIL-USDT",
})


def signed_positions(prices: np.ndarray, *, lookback: int = LOOKBACK,
                     vol_lookback: int = VOL_LOOKBACK,
                     threshold: float = THRESHOLD) -> np.ndarray:
    signal = np.asarray(time_series_momentum(
        prices, lookback=lookback, vol_lookback=vol_lookback,
    ), dtype=float)
    return np.where(signal >= threshold, 1.0,
                    np.where(signal <= -threshold, -1.0, 0.0))


async def run_fold(split_date: str, frames: dict, out_dir: Path,
                   threshold: float = THRESHOLD) -> dict:
    results = []
    for symbol, series in frames.items():
        prices = series.to_numpy(dtype=float)
        positions = signed_positions(prices, threshold=threshold)
        timestamps = [datetime.fromisoformat(date) for date in series.index]
        replay = await replay_symbol(
            symbol, timestamps, prices.tolist(), positions.tolist(), split_date, out_dir,
            position_fraction=POSITION_FRACTION, allow_short=True,
        )
        replay["benchmark_oos_return"] = buy_and_hold_return(series, split_date)
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


async def main_async(major_only: bool = False, threshold: float = THRESHOLD,
                     output: str = "data/crypto_tsmom_multifold_replay.json") -> int:
    as_of = datetime.now(UTC)
    symbols = [symbol for symbol in store.symbols(store.DAILY_BARS)
               if symbol_domain(symbol) == "crypto"
               and (not major_only or symbol in MAJOR_CRYPTO)]
    frames, rejected = read_frames(symbols, as_of)
    matrix = align_frames(frames)
    if len(frames) < 4 or matrix.shape[0] < 300:
        raise RuntimeError("insufficient clean crypto data")
    splits = fold_dates(list(matrix.index))
    out_dir = Path("data/.kernel_replay_crypto_tsmom")
    out_dir.mkdir(parents=True, exist_ok=True)
    folds = [await run_fold(split, frames, out_dir, threshold=threshold) for split in splits]
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "real_data_only": True,
        "execution_kernel": "modules.simulation.SimulationService",
        "strategy": {"family": "signed_time_series_momentum", "lookback": LOOKBACK,
                      "vol_lookback": VOL_LOOKBACK, "threshold": threshold,
                      "long_short": True},
        "execution_config": {"fee_bps": 20.0, "mid_penalty_bps": 10.0,
                              "allow_short": True, "position_fraction": POSITION_FRACTION},
        "universe": "crypto_clean_local_daily",
        "universe_filter": "major_crypto_predeclared" if major_only else "all_local_crypto",
        "symbols": len(frames),
        "quality_rejected": rejected,
        "candidate_family_size": 6,
        "selection_note": "exploratory local screen; kernel replay is not promotion evidence",
        "folds": folds,
        "status": "replay_only_not_promoted",
    }
    out = Path(output)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    print(json.dumps([{key: fold[key] for key in fold if key != "results"}
                      for fold in folds], ensure_ascii=False, indent=2))
    print(f"写入 {out}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--major-only", action="store_true",
                        help="use the predeclared major-crypto universe")
    parser.add_argument("--threshold", type=float, default=THRESHOLD)
    parser.add_argument("--output", default="data/crypto_tsmom_multifold_replay.json")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main_async(args.major_only, args.threshold, args.output)))
