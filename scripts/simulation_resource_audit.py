"""Audit resource bounds and shutdown hygiene of a real-kernel replay.

This intentionally runs a bounded slice of the local real BTC 1-minute dataset
through ``SimulationService``.  It is an operational audit, not strategy
evidence: the report separates resource and ledger invariants from PnL.
"""

from __future__ import annotations

import asyncio
import json
import os
import resource
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.dataset as ds

from modules.simulation import SimulationService
from modules.simulation import metrics as sim_metrics
from modules.simulation.sources import SimSignal

DATASET = Path("data/datasets/parts/btc_1m_bars_clean_v2/symbol=BTC-USDT")
DEFAULT_OUTPUT = Path("data/simulation_resource_audit.json")
CPU_BUDGET = 0.60


class Clock:
    def __init__(self, value: datetime):
        self.current = value

    def __call__(self) -> datetime:
        return self.current


def load_rows(limit: int) -> list[dict]:
    if limit < 10:
        raise ValueError("limit must be at least 10")
    if not DATASET.exists():
        raise RuntimeError(f"missing real dataset: {DATASET}")
    table = ds.dataset(DATASET, format="parquet").to_table(
        columns=["event_at", "close"]
    ).to_pylist()
    rows = sorted(table, key=lambda row: str(row["event_at"]))[:limit]
    if len(rows) < limit:
        raise RuntimeError(f"dataset has only {len(rows)} rows; need {limit}")
    return rows


def _ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


async def run_audit(rows: list[dict], work_dir: Path) -> dict:
    work_dir.mkdir(parents=True, exist_ok=True)
    before = {path.name for path in work_dir.iterdir()}
    db = work_dir / f"resource-audit-{uuid.uuid4().hex[:8]}.sqlite3"
    clock = Clock(_ts(str(rows[0]["event_at"])))
    service = SimulationService(db, clock=clock, equity_poll_seconds=10**9)
    started = time.monotonic()
    cpu_started = time.process_time()
    peak_rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    run_id = None
    raised: str | None = None
    try:
        await service.start()
        run = await service.create_run(
            name="resource-audit-btc-1m",
            strategy_id="signal_fusion",
            universe=["BTC-USDT"],
            initial_capital=10_000.0,
            config={
                "position_fraction": 0.05,
                "position_fraction_basis": "initial_capital",
                "fee_bps": 20.0,
                "mid_penalty_bps": 10.0,
                "allow_short": False,
                "cooldown_seconds": 0.0,
                "max_staleness_seconds": 600.0,
                "record_equity_on_fill": False,
                "record_equity_on_settlement": False,
                "min_cash_buffer": 0.0,
            },
        )
        run_id = str(run["run_id"])
        await service.start_run(run_id)
        for index, row in enumerate(rows):
            stamp = _ts(str(row["event_at"]))
            price = float(row["close"])
            clock.current = stamp
            # Alternating, deterministic signals exercise opening, closing and
            # repeated mark handling without claiming this is a strategy.
            side = "buy" if index % 20 == 0 else ("sell" if index % 20 == 10 else None)
            if side is not None:
                await service._process_signal(
                    service._active[run_id],
                    SimSignal(
                        instrument_id="BTC-USDT", side=side, confidence=1.0,
                        mid=price, timestamp=stamp,
                        signal_meta={"source": "resource_audit", "index": index},
                    ),
                )
            else:
                service._active[run_id].marks["BTC-USDT"] = price
            if index % 25 == 0 or index == len(rows) - 1:
                await service._record_equity(service._active[run_id])
            # Bound this single worker's average CPU share while preserving
            # the same synchronous fill and ledger path as the replay kernel.
            elapsed = time.monotonic() - started
            cpu = time.process_time() - cpu_started
            if elapsed > 0 and cpu / elapsed > 0.30:
                await asyncio.sleep(min(0.05, cpu / 0.30 - elapsed))
        await service.stop_run(run_id)
    except Exception as exc:  # report the failure, then still close the service
        raised = repr(exc)
    finally:
        await service.stop()

    elapsed = max(time.monotonic() - started, 1e-9)
    cpu_fraction = (time.process_time() - cpu_started) / elapsed
    peak_rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    leaked = sorted(path.name for path in work_dir.iterdir() if path.name not in before)
    metrics = sim_metrics.compute_run_metrics(service.store, run_id) if run_id else {}
    trades = len(service.store.list_trades(run_id)) if run_id else 0
    equity_points = len(service.store.list_equity_points(run_id)) if run_id else 0
    # The audit database is owned by this bounded run and is safe to remove
    # only after the service has closed all connections.
    for suffix in ("", "-wal", "-shm"):
        db.with_name(db.name + suffix).unlink(missing_ok=True)
    remaining = sorted(path.name for path in work_dir.iterdir() if path.name not in before)
    status = "PASS" if raised is None and not remaining and cpu_fraction <= CPU_BUDGET else "FAIL"
    return {
        "schema_version": "simulation-resource-audit-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": str(DATASET),
        "rows": len(rows),
        "status": status,
        "scope": "single-process local real-kernel audit; not strategy evidence",
        "resource_policy": {"cpu_budget_fraction": CPU_BUDGET, "worker_count": 1},
        "observed": {
            "wall_seconds": round(elapsed, 4),
            "process_cpu_fraction": round(cpu_fraction, 4),
            "maxrss_delta": int(peak_rss_after - peak_rss_before),
            "throughput_rows_per_second": round(len(rows) / elapsed, 2),
        },
        "ledger": {"run_id": run_id, "trades": trades, "equity_points": equity_points,
                   "metrics": metrics},
        "shutdown": {"exception": raised, "files_before": sorted(before),
                      "files_created_before_cleanup": leaked, "files_remaining": remaining},
    }


async def main_async(limit: int = 600, output: Path = DEFAULT_OUTPUT) -> int:
    rows = load_rows(limit)
    report = await run_audit(rows, Path("data/.resource_audit"))
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=600)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main_async(args.limit, args.output)))
