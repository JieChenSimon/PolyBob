"""Replay a cross-sectional signal through the real Paper Lab execution kernel."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from libs.data.universe import US_LIQUID
from modules.simulation import SimulationService
from modules.simulation import metrics as sim_metrics
from modules.simulation.sources import SimSignal
from scripts.cross_sectional_local_screen import align_frames, read_frames, select_long_only


class ReplayPositionSource:
    """Replay precomputed causal targets; no strategy decisions are changed."""

    topics = ("features.snapshots",)

    def __init__(self, config: dict):
        self.positions = [float(v) for v in config["replay_positions"]]
        self.index = 0
        self.previous = 0.0

    async def on_snapshot(self, topic: str, snapshot: dict) -> list[SimSignal]:
        if self.index >= len(self.positions):
            return []
        target = self.positions[self.index]
        self.index += 1
        if target == self.previous:
            return []
        self.previous = target
        return [SimSignal(
            instrument_id=str(snapshot["market_id"]),
            side="buy" if target > 0 else "sell",
            confidence=1.0,
            mid=float(snapshot["mid_price"]),
            timestamp=snapshot["timestamp"],
            signal_meta={"source": "cross_sectional_kernel_replay", "target": target},
        )]


class ReplayClock:
    def __init__(self, value: datetime):
        self.current = value

    def __call__(self) -> datetime:
        return self.current


async def replay_symbol(symbol: str, timestamps: list, prices: list[float], positions: list[float],
                        split_date: str, out_dir: Path) -> dict:
    timestamps = [datetime.fromisoformat(value) if isinstance(value, str) else value
                  for value in timestamps]
    timestamps = [value if value.tzinfo else value.replace(tzinfo=UTC) for value in timestamps]
    clock = ReplayClock(timestamps[0])
    db_path = out_dir / f"{symbol}-{uuid.uuid4().hex[:8]}.sqlite3"
    service = SimulationService(
        db_path,
        clock=clock,
        equity_poll_seconds=10**9,
        source_factories={"replay_positions": lambda config, _db: ReplayPositionSource(config)},
    )
    await service.start()
    run = await service.create_run(
        name=f"xs-kernel:{symbol}", strategy_id="replay_positions", universe=[symbol],
        initial_capital=10_000.0,
        config={
            "replay_positions": positions,
            "fee_bps": 20.0,
            "mid_penalty_bps": 10.0,
            "allow_short": False,
            "cooldown_seconds": 0.0,
            "max_staleness_seconds": 172800.0,
            "equity_interval_minutes": 1440.0,
        },
    )
    run_id = str(run["run_id"])
    await service.start_run(run_id)
    for timestamp, price in zip(timestamps, prices):
        clock.current = timestamp
        await service._dispatch("features.snapshots", {
            "market_id": symbol, "timestamp": timestamp, "mid_price": price,
            "source": "local_daily_bars", "price_basis": "unadjusted",
        })
        await service._record_equity(service._active[run_id])
    await service.stop_run(run_id)
    metrics = sim_metrics.compute_run_metrics(service.store, run_id)
    points = service.store.list_equity_points(run_id)
    oos_points = [point for point in points if point.ts >= split_date]
    prior_points = [point for point in points if point.ts < split_date]
    oos_start = prior_points[-1] if prior_points else (oos_points[0] if oos_points else None)
    oos_end = oos_points[-1] if oos_points else None
    oos_return = (
        oos_end.equity / oos_start.equity - 1.0
        if oos_start is not None and oos_end is not None and oos_start.equity > 0 else None
    )
    trades = service.store.list_trades(run_id)
    oos_closed = sum(1 for trade in trades if trade.executed_at >= split_date and trade.realized_pnl is not None)
    await service.stop()
    for suffix in ("", "-wal", "-shm"):
        db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)
    return {"symbol": symbol, "run_id": run_id, "metrics": metrics,
            "oos_return": oos_return, "oos_closed_trades": oos_closed,
            "oos_points": len(oos_points)}


async def main_async() -> int:
    as_of = datetime.now(UTC)
    frames, rejected = read_frames(list(US_LIQUID), as_of)
    symbols = list(frames)
    matrix_frame = align_frames(frames)
    matrix = matrix_frame.to_numpy(dtype=float).T
    if len(symbols) < 4 or matrix.shape[1] < 300:
        raise RuntimeError("insufficient clean liquid universe")
    positions = select_long_only(matrix, lookback=60, top_frac=0.3, rebalance_days=10)
    split_date = str(matrix_frame.index[int(matrix_frame.shape[0] * 0.7)])
    out_dir = Path("data/.kernel_replay")
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for symbol, target in zip(symbols, positions):
        series = frames[symbol]
        valid = series.index.isin(matrix_frame.index)
        aligned_target = target[[matrix_frame.index.get_loc(date) for date in series.index if date in matrix_frame.index]]
        timestamps = [datetime.fromisoformat(date) for date in series.index[valid]]
        results.append(await replay_symbol(symbol, timestamps, series.to_numpy(dtype=float).tolist(),
                                           aligned_target.tolist(), split_date, out_dir))
    returns = [item.get("oos_return") for item in results]
    returns = [float(value) for value in returns if value is not None]
    report = {
        "generated_at": datetime.now(UTC).isoformat(), "real_data_only": True,
        "execution_kernel": "modules.simulation.SimulationService",
        "strategy": {"lookback": 60, "top_frac": 0.3, "rebalance_days": 10},
        "execution_config": {"fee_bps": 20.0, "mid_penalty_bps": 10.0, "allow_short": False},
        "split_date": split_date, "symbols": len(symbols), "quality_rejected": rejected,
        "mean_kernel_oos_return": sum(returns) / len(returns) if returns else None,
        "median_kernel_oos_return": sorted(returns)[len(returns) // 2] if returns else None,
        "positive_oos_fraction": sum(value > 0 for value in returns) / len(returns) if returns else None,
        "results": results,
        "status": "replay_only_not_promoted",
    }
    out = Path("data/cross_sectional_kernel_replay.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    print(json.dumps({k: report[k] for k in ("symbols", "quality_rejected", "split_date", "mean_kernel_oos_return", "median_kernel_oos_return", "positive_oos_fraction", "status")}, ensure_ascii=False, indent=2))
    print(f"写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
