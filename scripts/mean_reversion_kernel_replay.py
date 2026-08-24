"""Replay a pre-registered mean-reversion candidate through Paper Lab."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from libs.data import store
from libs.data.universe import US_LIQUID
from scripts.cross_sectional_kernel_replay import replay_symbol
from scripts.cross_sectional_local_screen import align_frames, read_frames, symbol_domain
from scripts.mean_reversion_research import mean_reversion_positions


async def replay_domain(domain: str, symbols: list[str], as_of: datetime, out_dir: Path) -> dict:
    frames, rejected = read_frames(symbols, as_of)
    symbols = list(frames)
    matrix_frame = align_frames(frames)
    if len(symbols) < 4 or matrix_frame.shape[0] < 300:
        return {"domain": domain, "status": "blocked_insufficient_data", "symbols": len(symbols),
                "quality_rejected": rejected}
    split_date = str(matrix_frame.index[int(matrix_frame.shape[0] * 0.7)])
    results = []
    for symbol in symbols:
        series = frames[symbol]
        positions = mean_reversion_positions(series.to_numpy(dtype=float), lookback=20, entry_bps=100)
        timestamps = [datetime.fromisoformat(date) for date in series.index]
        results.append(await replay_symbol(
            symbol, timestamps, series.to_numpy(dtype=float).tolist(), positions.tolist(),
            split_date, out_dir,
        ))
    returns = [float(item["oos_return"]) for item in results if item.get("oos_return") is not None]
    return {
        "domain": domain, "status": "replay_only_not_promoted", "symbols": len(symbols),
        "quality_rejected": rejected, "split_date": split_date,
        "strategy": {"lookback": 20, "entry_bps": 100, "long_only": True},
        "mean_kernel_oos_return": sum(returns) / len(returns) if returns else None,
        "median_kernel_oos_return": sorted(returns)[len(returns) // 2] if returns else None,
        "positive_oos_fraction": sum(value > 0 for value in returns) / len(returns) if returns else None,
        "oos_closed_trade_median": sorted(item["oos_closed_trades"] for item in results)[len(results) // 2] if results else None,
        "results": results,
    }


async def main_async() -> int:
    as_of = datetime.now(UTC)
    all_symbols = store.symbols(store.DAILY_BARS)
    domains = {
        "us_equity": list(US_LIQUID),
        "a_share": [s for s in all_symbols if symbol_domain(s) == "a_share"],
        "crypto": [s for s in all_symbols if symbol_domain(s) == "crypto"],
    }
    out_dir = Path("data/.kernel_replay_mean_reversion")
    out_dir.mkdir(parents=True, exist_ok=True)
    report_domains = {domain: await replay_domain(domain, symbols, as_of, out_dir)
                      for domain, symbols in domains.items()}
    report = {
        "generated_at": datetime.now(UTC).isoformat(), "real_data_only": True,
        "execution_kernel": "modules.simulation.SimulationService",
        "execution_config": {"fee_bps": 20.0, "mid_penalty_bps": 10.0, "allow_short": False},
        "domains": report_domains, "status": "replay_only_not_promoted",
    }
    out = Path("data/mean_reversion_kernel_replay.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    print(json.dumps(report_domains, ensure_ascii=False, indent=2, default=str))
    print(f"写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
