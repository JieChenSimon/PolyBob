"""Replay a bounded, causal BTC 5-minute momentum family through Paper Lab.

This runner deliberately evaluates a small pre-registered family rather than
searching a large grid. It uses the same ``MomentumSignalSource`` and
``SimulationService`` as Paper Lab, with real local 1-minute bars aggregated to
5-minute observations. Historical executable depth is not inferred.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.dataset as ds
import pandas as pd
import structlog

from libs.quant.return_target import evaluate_return_target
from modules.simulation import SimulationService
from modules.simulation import metrics as sim_metrics


DATASET = Path(
    "data/datasets/compacted/btc_1m_bars_clean_v2/dataset/symbol=BTC-USDT"
)
PRE_REGISTERED = ((12, 36), (36, 72), (12, 72))
COST_MULTIPLES = (1.0, 2.0, 3.0)
EQUITY_SAMPLE_BARS = 20
CPU_TARGET = 0.45


class CpuBudgetThrottle:
    """Bound this research worker's average process CPU share."""

    def __init__(self, target: float = CPU_TARGET):
        self.target = max(0.05, min(0.50, target))
        self.wall = time.monotonic()
        self.cpu = time.process_time()

    def pause(self) -> None:
        elapsed_wall = time.monotonic() - self.wall
        elapsed_cpu = time.process_time() - self.cpu
        if elapsed_wall < 0.05 or elapsed_cpu <= 0:
            return
        desired_wall = elapsed_cpu / self.target
        if desired_wall > elapsed_wall:
            time.sleep(min(desired_wall - elapsed_wall, 1.0))
        self.wall = time.monotonic()
        self.cpu = time.process_time()


class Clock:
    def __init__(self, value: datetime):
        self.current = value

    def __call__(self) -> datetime:
        return self.current


def load_bars() -> list[dict]:
    if not DATASET.exists():
        raise RuntimeError(f"missing dataset: {DATASET}")
    frame = ds.dataset(DATASET, format="parquet").to_table(
        columns=["event_at", "close"]
    ).to_pandas()
    frame["event_at"] = pd.to_datetime(frame["event_at"], utc=True)
    frame = frame.sort_values("event_at").drop_duplicates("event_at")
    frame = frame.set_index("event_at").resample("5min").last().dropna()
    gap = frame.index.to_series().diff().dt.total_seconds().fillna(300)
    frame = frame[gap <= 300]
    return [
        {"event_at": stamp.to_pydatetime(), "close": float(row.close)}
        for stamp, row in frame.iterrows()
    ]


async def replay(
    bars: list[dict], fast_window: int, slow_window: int, cost_multiple: float,
    out_dir: Path,
) -> dict:
    db = out_dir / f"btc5m-momentum-{uuid.uuid4().hex[:8]}.sqlite3"
    clock = Clock(bars[0]["event_at"])
    service = SimulationService(db, clock=clock, equity_poll_seconds=10**9)
    try:
        await service.start()
        run = await service.create_run(
            name=f"btc5m-momentum:{fast_window}/{slow_window}:{cost_multiple:g}x",
            strategy_id="momentum_dualma_v1", universe=["BTC-USDT"],
            initial_capital=10_000.0,
            config={
                "fast_window": fast_window,
                "slow_window": slow_window,
                "min_separation_bps": 5.0,
                "momentum_confidence": 0.7,
                "position_fraction": 0.10,
                "position_fraction_basis": "initial_capital",
                "fee_bps": 20.0 * cost_multiple,
                "mid_penalty_bps": 10.0 * cost_multiple,
                "allow_short": True,
                "cooldown_seconds": 1800.0,
                "min_rebalance_bps": 50.0,
                "max_staleness_seconds": 1800.0,
                "equity_interval_minutes": 5.0,
                "record_equity_on_fill": False,
            },
        )
        run_id = str(run["run_id"])
        await service.start_run(run_id)
        active = service._active[run_id]
        throttle = CpuBudgetThrottle()
        for index, bar in enumerate(bars, start=1):
            clock.current = bar["event_at"]
            await service._dispatch("features.snapshots", {
                "market_id": "BTC-USDT", "timestamp": bar["event_at"],
                "mid_price": bar["close"], "source": "btc_1m_bars_clean_v2",
                "price_basis": "close",
            })
            if index % EQUITY_SAMPLE_BARS == 0:
                await service._record_equity(active)
            throttle.pause()
        await service._record_equity(active)
        await service.stop_run(run_id)
        points = service.store.list_equity_points(run_id)
        split = bars[0]["event_at"] + (bars[-1]["event_at"] - bars[0]["event_at"]) * 0.70
        def point_ts(point) -> datetime:
            value = point.ts
            if isinstance(value, str):
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return value if value.tzinfo else value.replace(tzinfo=UTC)

        before = [point for point in points if point_ts(point) < split]
        after = [point for point in points if point_ts(point) >= split]
        oos_return = None
        if before and after and before[-1].equity > 0:
            oos_return = after[-1].equity / before[-1].equity - 1.0
        active = service._active.get(run_id)
        return {
            "fast_window": fast_window, "slow_window": slow_window,
            "cost_multiple": cost_multiple, "bars": len(bars),
            "metrics": sim_metrics.compute_run_metrics(service.store, run_id),
            "return_target": evaluate_return_target(points).to_dict(),
            "oos_return": oos_return,
            "trades": len(service.store.list_trades(run_id)),
            "risk_rejections": int(active.risk_rejections) if active else None,
            "execution_evidence": "historical_depth_unknown",
        }
    finally:
        await service.stop()
        for suffix in ("", "-wal", "-shm"):
            db.with_name(db.name + suffix).unlink(missing_ok=True)


async def main_async() -> int:
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))
    bars = load_bars()
    if len(bars) < 1_000:
        raise RuntimeError(f"insufficient 5m bars: {len(bars)}")
    out_dir = Path("data/.kernel_replay_btc5m_momentum")
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    results = []
    for fast, slow in PRE_REGISTERED:
        for multiple in COST_MULTIPLES:
            results.append(await replay(bars, fast, slow, multiple, out_dir))
            print(json.dumps({"completed": len(results), "total": len(PRE_REGISTERED) * len(COST_MULTIPLES),
                              "fast": fast, "slow": slow, "cost": multiple,
                              "elapsed_seconds": round(time.monotonic() - started, 2)}), flush=True)
    report = {
        "schema_version": "btc5m-momentum-kernel-replay-v1",
        "generated_at": datetime.now(UTC).isoformat(), "real_data_only": True,
        "research_only": True, "strategy": "btc5m_dual_moving_average_momentum",
        "dataset": str(DATASET), "bars": len(bars),
        "coverage": {"start": bars[0]["event_at"].isoformat(), "end": bars[-1]["event_at"].isoformat(),
                     "independent_days": len({bar["event_at"].date() for bar in bars})},
        "pre_registered_family": [list(item) for item in PRE_REGISTERED],
        "cost_multiples": list(COST_MULTIPLES), "results": results,
        "promotion": {"status": "BLOCKED", "reason": "short_history_and_historical_depth_unknown"},
    }
    output = Path("/tmp/polybob-btc5m-momentum-kernel.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "promotion": report["promotion"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
