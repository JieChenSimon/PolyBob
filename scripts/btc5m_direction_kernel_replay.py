"""Replay a causal BTC 5-minute direction rule through the real simulation kernel."""

from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import logging
import json
import math
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pyarrow.dataset as ds
import structlog

# Keep numerical libraries from creating their own thread pools inside each
# replay worker.  The replay is deliberately bounded below 60% of a typical
# development machine's logical CPU capacity; it is a background research job,
# not an excuse to starve the rest of the workstation.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

# A replay can generate tens of thousands of fills.  INFO-level per-fill logs
# turn the terminal and stderr pipe into the bottleneck, so retain warnings and
# errors while the explicit progress reporter below remains visible.
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
    logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    cache_logger_on_first_use=False,
)

from libs.quant.promotion import PromotionGate
from libs.quant.return_target import evaluate_return_target
from modules.simulation import SimulationService
from modules.simulation import metrics as sim_metrics
from modules.simulation.sources import SimSignal

_RAW_DATASET = Path("data/datasets/parts/btc_1m_bars_clean_v2/symbol=BTC-USDT")
_COMPACTED_DATASET = Path(
    "data/datasets/compacted/btc_1m_bars_clean_v2/dataset/symbol=BTC-USDT"
)
DATASET = _COMPACTED_DATASET if _COMPACTED_DATASET.exists() else _RAW_DATASET
THRESHOLDS = (0.55, 0.60, 0.65)
SPLITS = (0.50, 0.60, 0.70, 0.80)
COSTS = (1.0, 2.0, 3.0)
EQUITY_SAMPLE_EVENTS = 20


def replay_worker(args: tuple[list[dict], float, str, float, Path]) -> dict:
    """Run one isolated cost scenario in a bounded worker process."""
    return asyncio.run(replay(*args))


def worker_budget() -> int:
    """Return a conservative worker count with a hard project-side ceiling."""
    logical = os.cpu_count() or 1
    configured = int(os.environ.get("POLYBOB_REPLAY_WORKERS", "0") or 0)
    # Default to four workers for useful multicore throughput.  The hard
    # project-side ceiling is six workers and 50% of logical CPUs, leaving the
    # other half for the API, browser, editor and the OS. A caller can lower
    # this, never raise it.
    safe_capacity = max(1, int(logical * 0.50))
    return max(1, min(6, safe_capacity, configured or 4))


def write_progress(path: Path, *, completed: int, total: int, started: float,
                   current: str | None = None) -> None:
    """Persist human-readable progress without treating partial work as evidence."""
    elapsed = max(0.0, time.monotonic() - started)
    rate = completed / elapsed if elapsed > 0 else 0.0
    remaining = (total - completed) / rate if rate > 0 else None
    payload = {
        "status": "running" if completed < total else "completed",
        "completed_scenarios": completed,
        "total_scenarios": total,
        "fraction": completed / total if total else 1.0,
        "elapsed_seconds": round(elapsed, 3),
        "eta_seconds": round(remaining, 3) if remaining is not None else None,
        "current": current,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    width = 28
    filled = int(width * payload["fraction"])
    eta = f" ETA {remaining / 60:.1f}m" if remaining is not None else " ETA --"
    print(
        f"replay progress [{'#' * filled}{'-' * (width - filled)}] "
        f"{completed}/{total} ({payload['fraction']:.1%}) elapsed {elapsed / 60:.1f}m{eta}"
        + (f" current={current}" if current else ""),
        flush=True,
    )


def oos_daily_returns(points: list, split: str) -> list[float]:
    """Build non-overlapping daily OOS returns from the persisted equity curve."""
    endpoints: dict[str, float] = {}
    for point in points:
        ts = point.ts
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        day = ts.date().isoformat()
        endpoints[day] = float(point.equity)  # points are chronological
    days = sorted(endpoints)
    start_index = next((i for i, day in enumerate(days) if day >= split), len(days))
    if start_index == 0 or start_index >= len(days):
        return []
    previous = endpoints[days[start_index - 1]]
    returns: list[float] = []
    for day in days[start_index:]:
        current = endpoints[day]
        if previous > 0:
            returns.append(current / previous - 1.0)
        previous = current
    return returns


class Clock:
    def __init__(self, value: datetime):
        self.current = value

    def __call__(self) -> datetime:
        return self.current


class ReplaySource:
    topics = ("features.snapshots",)

    def __init__(self, config: dict):
        self.targets = [float(v) for v in config["targets"]]
        self.index = 0
        self.previous = 0.0

    async def on_snapshot(self, topic: str, snapshot: dict) -> list[SimSignal]:
        if self.index >= len(self.targets):
            return []
        target = self.targets[self.index]
        self.index += 1
        if target == self.previous:
            return []
        previous = self.previous
        self.previous = target
        side = "buy" if target > previous else "sell"
        return [SimSignal(
            instrument_id="BTC-USDT", side=side, confidence=1.0,
            mid=float(snapshot["mid_price"]), timestamp=snapshot["timestamp"],
            signal_meta={"source": "btc5m_direction_kernel_replay", "target": target},
        )]


def load_windows() -> list[dict]:
    if not DATASET.exists():
        raise RuntimeError(f"missing materialized dataset: {DATASET}")
    table = ds.dataset(DATASET, format="parquet").to_table(
        columns=["event_at", "open", "close"]
    ).to_pandas().sort_values("event_at")
    table["ts"] = table["event_at"].map(lambda value: datetime.fromisoformat(value).replace(tzinfo=UTC))
    closes = table["close"].to_numpy(dtype=float)
    logret = np.diff(np.log(closes), prepend=np.log(closes[0]))
    rows = []
    for start in range(30, len(table) - 4, 5):
        chunk = table.iloc[start:start + 5]
        if len(chunk) != 5:
            continue
        stamps = chunk["ts"].tolist()
        if any((stamps[i + 1] - stamps[i]).total_seconds() != 60 for i in range(4)):
            continue
        sigma = float(np.std(logret[start - 30:start], ddof=1))
        if not np.isfinite(sigma) or sigma <= 0:
            continue
        entry = float(chunk.iloc[2]["close"])
        final = float(chunk.iloc[4]["close"])
        probability = 0.5 * (1.0 + math.erf(
            float(np.log(entry / float(chunk.iloc[0]["open"]))
                  / (sigma * np.sqrt(2.0 * 2.0)))
        ))
        rows.append({"entry_ts": stamps[2], "exit_ts": stamps[4], "entry": entry,
                     "final": final, "probability": probability,
                     "date": stamps[0].date().isoformat()})
    return rows


async def replay(rows: list[dict], threshold: float, split: str, multiple: float, out_dir: Path) -> dict:
    timestamps: list[datetime] = []
    prices: list[float] = []
    targets: list[float] = []
    for row in rows:
        direction = 0.10 if row["probability"] >= threshold else (-0.10 if row["probability"] <= 1.0 - threshold else 0.0)
        timestamps.extend([row["entry_ts"], row["exit_ts"]])
        prices.extend([row["entry"], row["final"]])
        targets.extend([direction, 0.0])
    clock = Clock(timestamps[0])
    db = out_dir / f"btc5m-{uuid.uuid4().hex[:8]}.sqlite3"
    service = SimulationService(
        db, clock=clock, equity_poll_seconds=10**9,
        source_factories={"btc5m_replay": lambda config, _db: ReplaySource(config)},
    )
    await service.start()
    run = await service.create_run(
        name=f"btc5m-direction:{threshold}", strategy_id="btc5m_replay", universe=["BTC-USDT"],
        initial_capital=10_000.0,
        config={"targets": targets, "position_fraction": 0.10, "fee_bps": 20.0 * multiple,
                "mid_penalty_bps": 10.0 * multiple, "allow_short": True,
                "cooldown_seconds": 0.0, "max_staleness_seconds": 600.0,
                "equity_interval_minutes": 1.0,
                "record_equity_on_fill": False},
    )
    run_id = str(run["run_id"])
    await service.start_run(run_id)
    for event_index, (timestamp, price) in enumerate(zip(timestamps, prices), start=1):
        clock.current = timestamp
        await service._dispatch("features.snapshots", {
            "market_id": "BTC-USDT", "timestamp": timestamp, "mid_price": price,
            "source": "btc_1m_bars", "price_basis": "close",
        })
        # Preserve the full fill and ledger path, but sample the expensive
        # equity projection at a bounded cadence for this high-throughput
        # replay.  The final point is always recorded below.
        if event_index % EQUITY_SAMPLE_EVENTS == 0:
            await service._record_equity(service._active[run_id])
    await service._record_equity(service._active[run_id])
    await service.stop_run(run_id)
    trade_count = len(service.store.list_trades(run_id))
    metrics = sim_metrics.compute_run_metrics(service.store, run_id)
    points = service.store.list_equity_points(run_id)
    return_target = evaluate_return_target(points)
    prior = [p for p in points if p.ts < split]
    future = [p for p in points if p.ts >= split]
    start = prior[-1] if prior else (future[0] if future else None)
    end = future[-1] if future else None
    oos_return = end.equity / start.equity - 1.0 if start and end and start.equity > 0 else None
    daily_oos_returns = oos_daily_returns(points, split)
    await service.stop()
    for suffix in ("", "-wal", "-shm"):
        db.with_name(db.name + suffix).unlink(missing_ok=True)
    return {"threshold": threshold, "cost_multiple": multiple, "split_date": split,
            "oos_return": oos_return, "metrics": metrics,
            "return_target": return_target.to_dict(),
            "trades": trade_count,
            "oos_daily_returns": daily_oos_returns}


async def main_async() -> int:
    rows = load_windows()
    if len(rows) < 1_000:
        raise RuntimeError(f"insufficient windows: {len(rows)}")
    dates = [row["date"] for row in rows]
    splits = [dates[int(len(dates) * fraction)] for fraction in SPLITS]
    out_dir = Path("data/.kernel_replay_btc5m_direction")
    out_dir.mkdir(parents=True, exist_ok=True)
    progress_path = out_dir / "progress.json"
    total_scenarios = len(THRESHOLDS) * len(splits) * len(COSTS)
    started = time.monotonic()
    completed_scenarios = 0
    write_progress(progress_path, completed=0, total=total_scenarios, started=started)
    results = {}
    workers = worker_budget()
    print(f"replay resource policy: workers={workers}, logical_cpus={os.cpu_count() or 1}, cpu_budget<=60%")
    loop = asyncio.get_running_loop()
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
        async def run_scenario(threshold: float, split: str, multiple: float) -> tuple[float, str, float, dict]:
            result = await loop.run_in_executor(
                pool,
                functools.partial(replay_worker, (rows, threshold, split, multiple, out_dir)),
            )
            return threshold, split, multiple, result

        jobs = [
            asyncio.create_task(run_scenario(threshold, split, multiple))
            for threshold in THRESHOLDS
            for split in splits
            for multiple in COSTS
        ]
        completed_results: dict[tuple[float, str, float], dict] = {}
        for finished in asyncio.as_completed(jobs):
            threshold, split, multiple, result = await finished
            completed_results[(threshold, split, multiple)] = result
            completed_scenarios += 1
            write_progress(
                progress_path,
                completed=completed_scenarios,
                total=total_scenarios,
                started=started,
                current=f"threshold={threshold} split={split} cost={multiple}",
            )

        for threshold in THRESHOLDS:
            folds = []
            for split in splits:
                costs = [completed_results[(threshold, split, multiple)] for multiple in COSTS]
                folds.append({"split_date": split, "costs": costs})
            base = [f["costs"][0]["oos_return"] for f in folds]
            base = [float(value) for value in base if value is not None]
            stability = float(np.mean(np.asarray(base) > 0)) if base else 0.0
            gate_returns = list(folds[0]["costs"][0].get("oos_daily_returns") or [])
            gate = PromotionGate(n_trials=len(THRESHOLDS) * len(COSTS), min_dsr=.90,
                                 min_observations=200, min_oos_stability_rate=.5,
                                 cost_min_sharpe=.3).evaluate(
                gate_returns,
                cost_returns_fn=lambda multiple: list(
                    folds[0]["costs"][COSTS.index(multiple)].get("oos_daily_returns") or []
                ),
                cost_multiples=COSTS, oos_stability_rate=stability,
            )
            results[str(threshold)] = {"folds": folds, "promotion": gate.to_dict()}
    report = {"generated_at": datetime.now(UTC).isoformat(), "real_data_only": True,
              "strategy": "btc5m_spot_direction_proxy",
              "product_scope": "BTC-USDT spot proxy; not a Polymarket UP/DOWN event contract",
              "tradable_evidence": False,
              "dataset": str(DATASET), "windows": len(rows),
              "resource_policy": {"workers": workers, "cpu_budget": "<=60%"},
              "equity_sampling": {"events": EQUITY_SAMPLE_EVENTS, "record_equity_on_fill": False},
              "thresholds": list(THRESHOLDS), "cost_multiples": list(COSTS),
              "results": results, "status": "replay_only_not_promoted"}
    out = Path("data/btc5m_direction_kernel_replay.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    write_progress(progress_path, completed=total_scenarios, total=total_scenarios,
                   started=started, current="report_written")
    print(json.dumps({key: value["promotion"] for key, value in results.items()}, ensure_ascii=False, indent=2))
    print(f"写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
