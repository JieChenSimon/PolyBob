"""Replay BTC 5m event candidates through the real paper-fill kernel.

This is an execution diagnostic, not promotion evidence: the historical CLOB
endpoint supplies a price history rather than executable bid/ask/depth. The
replay therefore uses a fixed spread stress around the recorded probability and
labels the result accordingly. Positions, fees, cash, settlement and equity are
still processed by :class:`SimulationService`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.dataset as ds
import structlog

from modules.simulation import SimulationService
from modules.simulation import metrics as sim_metrics
from modules.simulation.sources import SimSignal

DATASET = Path("data/datasets/parts/btc5m_settled_windows_v6/symbol=BTC-USDT")
COST_MULTIPLES = (1.0, 2.0, 3.0)
EDGE_THRESHOLD = 0.10
SPREAD_BPS = 50.0
EQUITY_SAMPLE_EVENTS = max(1, int(os.environ.get("POLYBOB_BTC5M_EQUITY_SAMPLE_EVENTS", "20")))
REPLAY_THROTTLE_SECONDS = max(0.0, float(os.environ.get("POLYBOB_BTC5M_REPLAY_THROTTLE_SECONDS", "0.20")))
REPLAY_CHUNK_ROWS = max(1, int(os.environ.get("POLYBOB_BTC5M_REPLAY_CHUNK_ROWS", "100")))
REPLAY_CPU_TARGET = min(0.50, max(0.05, float(os.environ.get("POLYBOB_BTC5M_REPLAY_CPU_TARGET", "0.30"))))
REPLAY_CPU_WINDOW_SECONDS = max(
    0.02, float(os.environ.get("POLYBOB_BTC5M_REPLAY_CPU_WINDOW_SECONDS", "0.05"))
)
REPLAY_MIN_SLEEP_SECONDS = max(
    0.01, float(os.environ.get("POLYBOB_BTC5M_REPLAY_MIN_SLEEP_SECONDS", "0.10"))
)
REPLAY_SQLITE_SYNCHRONOUS = os.environ.get("POLYBOB_BTC5M_SQLITE_SYNCHRONOUS", "NORMAL").upper()
REPLAY_SQLITE_WAL_AUTOCHECKPOINT = max(
    1000, int(os.environ.get("POLYBOB_BTC5M_SQLITE_WAL_AUTOCHECKPOINT", "10000"))
)


class CpuBudgetThrottle:
    """Keep this worker's average CPU share bounded during SQLite-heavy replay.

    ``ps`` reports an instantaneous process percentage, so a fixed sleep is
    not sufficient: bursts during a large transaction can still exceed the
    workstation budget.  This controller compares process CPU time with wall
    time and sleeps until the configured worker share is restored.
    """

    def __init__(self, target: float = REPLAY_CPU_TARGET):
        self.target = min(0.50, max(0.05, float(target)))
        self._wall = time.monotonic()
        self._cpu = time.process_time()

    def pause(self) -> None:
        wall = time.monotonic() - self._wall
        cpu = time.process_time() - self._cpu
        if wall < REPLAY_CPU_WINDOW_SECONDS or cpu <= 0:
            return
        desired_wall = cpu / self.target
        if desired_wall > wall:
            time.sleep(min(desired_wall - wall, 2.0))
        self._wall = time.monotonic()
        self._cpu = time.process_time()


def _checkpoint_path(out_dir: Path, multiple: float) -> Path:
    return out_dir / f"btc5m-event-{multiple:g}x.checkpoint.json"


def _write_checkpoint(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def _cleanup_orphan_databases(out_dir: Path) -> None:
    """Remove only replay databases not referenced by a live checkpoint."""
    referenced = {
        str(json.loads(path.read_text()).get("db"))
        for path in out_dir.glob("*.checkpoint.json")
        if path.is_file()
    }
    for database in out_dir.glob("*.sqlite3"):
        if str(database) not in referenced:
            for suffix in ("", "-wal", "-shm"):
                database.with_name(database.name + suffix).unlink(missing_ok=True)


class Clock:
    def __init__(self, value: datetime):
        self.current = value

    def __call__(self) -> datetime:
        return self.current


class EventReplaySource:
    topics = ("features.snapshots",)

    async def on_snapshot(self, topic: str, snapshot: dict) -> list[SimSignal]:
        side = snapshot.get("signal_side")
        if side not in {"buy", "sell"}:
            return []
        return [SimSignal(
            instrument_id=str(snapshot["market_id"]), side=side, confidence=1.0,
            bid=float(snapshot["bid_price"]), ask=float(snapshot["ask_price"]),
            mid=float(snapshot["mid_price"]),
            timestamp=snapshot["timestamp"],
            signal_meta=dict(snapshot.get("signal_meta") or {}),
        )]


def load_rows() -> list[dict]:
    if not DATASET.exists():
        raise RuntimeError(f"missing v6 dataset: {DATASET}")
    table = ds.dataset(DATASET, format="parquet").to_table().to_pylist()
    return sorted(table, key=lambda row: int(row["window_start"]))


def _quote(probability: float, multiple: float) -> tuple[float, float, float]:
    half_spread = SPREAD_BPS * multiple / 20_000.0
    mid = min(0.9999, max(0.0001, float(probability)))
    bid = max(0.0001, mid - half_spread)
    ask = min(0.9999, mid + half_spread)
    return bid, ask, mid


def _candidate_instrument(row: dict) -> str | None:
    edge = float(row["model_probability"]) - float(row["market_probability"])
    if abs(edge) < EDGE_THRESHOLD:
        return None
    direction = "UP" if edge >= EDGE_THRESHOLD else "DOWN"
    return f"BTC5M:{row['window_start']}:{direction}"


async def replay(rows: list[dict], multiple: float, out_dir: Path) -> dict:
    """Replay one cost case in resumable chunks with idempotent event keys."""
    if not rows:
        raise ValueError("rows must not be empty")
    if REPLAY_SQLITE_SYNCHRONOUS not in {"OFF", "NORMAL", "FULL", "EXTRA"}:
        raise ValueError(f"unsupported replay SQLite synchronous mode: {REPLAY_SQLITE_SYNCHRONOUS}")
    os.environ["POLYBOB_SQLITE_SYNCHRONOUS"] = REPLAY_SQLITE_SYNCHRONOUS
    os.environ["POLYBOB_SQLITE_WAL_AUTOCHECKPOINT"] = str(REPLAY_SQLITE_WAL_AUTOCHECKPOINT)
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING)
    )
    first = datetime.fromtimestamp(int(rows[0]["decision_ts"]), tz=UTC)
    clock = Clock(first)
    universe = sorted({
        instrument for row in rows
        if (instrument := _candidate_instrument(row)) is not None
    })
    if not universe:
        raise RuntimeError("no candidate instruments in replay rows")
    checkpoint = _checkpoint_path(out_dir, multiple)
    state: dict = {}
    if checkpoint.exists():
        state = json.loads(checkpoint.read_text())
        if state.get("rows") != len(rows) or float(state.get("cost_multiple")) != float(multiple):
            raise RuntimeError(f"checkpoint does not match replay input: {checkpoint}")
    db = Path(state.get("db") or (out_dir / f"btc5m-event-{uuid.uuid4().hex[:8]}.sqlite3"))
    # Existing checkpoint databases are already WAL databases. Avoid repeating
    # the journal-mode negotiation on every short-lived store connection.
    if db.exists():
        os.environ["POLYBOB_SQLITE_SKIP_JOURNAL_PRAGMA"] = "1"
    next_index = int(state.get("next_index", 0))
    settlement_failures = list(state.get("settlement_failures", []))
    settlement_skipped = int(state.get("settlement_skipped", 0))
    chunks = 0
    throttle = CpuBudgetThrottle()

    async def open_service() -> tuple[SimulationService, str]:
        service = SimulationService(
            db, clock=clock, equity_poll_seconds=10**9,
            source_factories={"btc5m_event_replay": lambda config, _db: EventReplaySource()},
        )
        await service.start()
        run_id = state.get("run_id")
        if run_id:
            await service.restore_state()
            active = service._active.get(str(run_id))
            if active is None:
                await service.stop()
                raise RuntimeError(f"checkpoint run cannot be restored: {run_id}")
            if active.record.status == "paused":
                await service.start_run(str(run_id))
            return service, str(run_id)
        run = await service.create_run(
            name=f"btc5m-event-kernel:{multiple}x",
            strategy_id="btc5m_event_replay", universe=universe,
            initial_capital=10_000.0,
            config={
                "position_fraction": 0.10, "position_fraction_basis": "initial_capital",
                "fee_bps": 0.0, "mid_penalty_bps": 0.0, "allow_short": False,
                "cooldown_seconds": 0.0, "max_staleness_seconds": 600.0,
                "min_trade_notional": 0.0, "equity_interval_minutes": 1.0,
                "record_equity_on_fill": False,
                "record_equity_on_settlement": False,
                "min_cash_buffer": 0.0,
            },
        )
        run_id = str(run["run_id"])
        await service.start_run(run_id)
        state.update({"rows": len(rows), "cost_multiple": multiple, "db": str(db), "run_id": run_id})
        _write_checkpoint(checkpoint, {**state, "next_index": 0})
        return service, run_id

    while next_index < len(rows):
        service, run_id = await open_service()
        existing_settlements = {
            item.settlement_id for item in service.store.list_settlements(run_id)
        }
        existing_trade_instruments = {
            item.instrument_id for item in service.store.list_trades(run_id)
        }
        active = service._active[run_id]
        end_index = min(len(rows), next_index + REPLAY_CHUNK_ROWS)
        for row_index in range(next_index, end_index):
            row = rows[row_index]
            edge = float(row["model_probability"]) - float(row["market_probability"])
            if abs(edge) < EDGE_THRESHOLD:
                continue
            buy_up = edge >= EDGE_THRESHOLD
            direction = "UP" if buy_up else "DOWN"
            settlement_id = f"btc5m:{row['window_start']}:{direction}"
            instrument = f"BTC5M:{row['window_start']}:{direction}"
            if settlement_id in existing_settlements:
                continue
            probability = float(row["market_probability"] if buy_up else 1.0 - row["market_probability"])
            outcome = int(row["outcome_up"] if buy_up else 1 - row["outcome_up"])
            entry_ts = datetime.fromtimestamp(int(row["decision_ts"]), tz=UTC)
            settle_ts = datetime.fromtimestamp(int(row["window_end"]), tz=UTC)
            bid, ask, mid = _quote(probability, multiple)
            clock.current = entry_ts
            if instrument not in existing_trade_instruments:
                await service._dispatch("features.snapshots", {
                    "market_id": instrument, "timestamp": entry_ts,
                    "mid_price": mid, "bid_price": bid, "ask_price": ask,
                    "signal_side": "buy",
                    "signal_meta": {
                        "source": "btc5m_event_kernel_diagnostic",
                        "execution_stage": "entry", "window_start": row["window_start"],
                        "raw_sha256": {
                            "gamma": row.get("gamma_raw_sha256"),
                            "clob": row.get("clob_raw_sha256"),
                            "okx": row.get("okx_raw_sha256"),
                        },
                        "execution_basis": "historical_probability_plus_fixed_spread_stress",
                        "quote_source": "synthetic_probability_stress",
                    },
                })
                existing_trade_instruments.add(instrument)
            position = service.store.get_position(run_id, instrument)
            if position is None or position.size <= 0:
                settlement_skipped += 1
                continue
            clock.current = settle_ts
            try:
                await service.settle_binary_position(
                    run_id, settlement_id=settlement_id,
                    market_id=f"BTC5M:{row['window_start']}", instrument_id=instrument,
                    quantity=position.size, payout_per_token=1.0 if outcome else 0.0,
                    settled_at=settle_ts.isoformat(), metadata={
                        "source": "btc5m_event_kernel_diagnostic",
                        "execution_stage": "settlement", "window_start": row["window_start"],
                        "raw_sha256": {
                            "gamma": row.get("gamma_raw_sha256"),
                            "clob": row.get("clob_raw_sha256"),
                            "okx": row.get("okx_raw_sha256"),
                        },
                        "execution_basis": "binary_payout_0_or_1; no_sell_fill",
                    },
                )
                existing_settlements.add(settlement_id)
            except Exception as exc:
                settlement_failures.append({"instrument": instrument, "error": str(exc)})
            time.sleep(max(REPLAY_THROTTLE_SECONDS, REPLAY_MIN_SLEEP_SECONDS))
            throttle.pause()
        next_index = end_index
        await service._record_equity(active)
        if next_index < len(rows):
            await service.pause_run(run_id)
            await service.stop()
            state.update({
                "next_index": next_index,
                "settlement_failures": settlement_failures,
                "settlement_skipped": settlement_skipped,
            })
            _write_checkpoint(checkpoint, state)
            chunks += 1
            continue

        await service.stop_run(run_id)
        metrics = sim_metrics.compute_run_metrics(service.store, run_id)
        settlements_for_split = service.store.list_settlements(run_id)
        pnl_by_day: dict[str, float] = {}
        for settlement in settlements_for_split:
            day = str(settlement.settled_at)[:10]
            pnl_by_day[day] = pnl_by_day.get(day, 0.0) + float(settlement.realized_pnl)
        split_days = sorted(pnl_by_day)
        split_at = max(1, min(len(split_days) - 1, int(len(split_days) * 0.70))) if len(split_days) > 1 else len(split_days)
        in_sample_days = split_days[:split_at]
        oos_days = split_days[split_at:]
        time_split = {
            "method": "chronological_70_30_by_settlement_day",
            "independent_days": len(split_days),
            "in_sample": {
                "days": len(in_sample_days),
                "start": in_sample_days[0] if in_sample_days else None,
                "end": in_sample_days[-1] if in_sample_days else None,
                "realized_pnl": sum(pnl_by_day[day] for day in in_sample_days),
                "return_on_initial_capital": (
                    sum(pnl_by_day[day] for day in in_sample_days) / 10_000.0
                ),
            },
            "out_of_sample": {
                "days": len(oos_days),
                "start": oos_days[0] if oos_days else None,
                "end": oos_days[-1] if oos_days else None,
                "realized_pnl": sum(pnl_by_day[day] for day in oos_days),
                "return_on_initial_capital": (
                    sum(pnl_by_day[day] for day in oos_days) / 10_000.0
                ),
            },
        }
        trades = len(service.store.list_trades(run_id))
        settlements = len(service.store.list_settlements(run_id))
        active = service._active.get(run_id)
        risk_rejections = active.risk_rejections if active is not None else 0
        rejection_events = active.risk_rejection_events if active is not None else []
        rejection_reasons = Counter(
            reason for event in rejection_events for reason in event.get("reasons", [])
        )
        rejection_by_stage = Counter(
            event.get("stage", "unknown") for event in rejection_events
        )
        open_positions = len(service.store.list_positions(run_id))
        unresolved_positions = [
            {"instrument": position.instrument_id, "size": position.size,
             "avg_price": position.avg_price}
            for position in service.store.list_positions(run_id)
        ]
        await service.stop()
        for suffix in ("", "-wal", "-shm"):
            db.with_name(db.name + suffix).unlink(missing_ok=True)
        checkpoint.unlink(missing_ok=True)
        return {
            "cost_multiple": multiple, "candidate_events": trades,
            "fills": trades, "settlements": settlements,
            "settlement_skipped": settlement_skipped,
            "settlement_failures": settlement_failures,
            "risk_rejections": risk_rejections,
            "risk_rejection_reasons": dict(rejection_reasons),
            "risk_rejections_by_stage": dict(rejection_by_stage),
            "open_positions": open_positions,
            "unresolved_positions": unresolved_positions,
            "chunks": chunks + 1,
            "time_split": time_split,
            "metrics": metrics,
        }
    raise RuntimeError("replay ended without a final result")


async def main_async() -> int:
    rows = load_rows()
    if len(rows) < 60:
        raise RuntimeError(f"insufficient v6 rows: {len(rows)}")
    out_dir = Path("data/.kernel_replay_btc5m_event")
    out_dir.mkdir(parents=True, exist_ok=True)
    _cleanup_orphan_databases(out_dir)
    report = {
        "generated_at": datetime.now(UTC).isoformat(), "real_data_only": True,
        "strategy": "btc5m_event_kernel_diagnostic",
        "tradable_evidence": False,
        "historical_execution_evidence": "missing",
        "historical_quote_depth": "unavailable",
        "execution_basis": "historical midpoint plus fixed spread stress; not executable CLOB ask/depth",
        "dataset": str(DATASET), "rows": len(rows),
        "edge_threshold": EDGE_THRESHOLD, "spread_bps": SPREAD_BPS,
        "equity_sample_events": EQUITY_SAMPLE_EVENTS,
        "replay_throttle_seconds": REPLAY_THROTTLE_SECONDS,
        "sqlite_synchronous": REPLAY_SQLITE_SYNCHRONOUS,
        "sqlite_wal_autocheckpoint": REPLAY_SQLITE_WAL_AUTOCHECKPOINT,
        "results": [await replay(rows, multiple, out_dir) for multiple in COST_MULTIPLES],
        "status": "diagnostic_not_promotion",
    }
    out = Path("data/btc5m_event_kernel_replay.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    print(json.dumps(report["results"], ensure_ascii=False, indent=2, default=str))
    print(f"写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
