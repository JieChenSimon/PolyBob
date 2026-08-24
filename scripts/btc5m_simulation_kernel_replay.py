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
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.dataset as ds

from modules.simulation import SimulationService
from modules.simulation import metrics as sim_metrics
from modules.simulation.sources import SimSignal

DATASET = Path("data/datasets/parts/btc5m_settled_windows_v5/symbol=BTC-USDT")
COST_MULTIPLES = (1.0, 2.0, 3.0)
EDGE_THRESHOLD = 0.10
SPREAD_BPS = 50.0


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
        raise RuntimeError(f"missing v5 dataset: {DATASET}")
    table = ds.dataset(DATASET, format="parquet").to_table().to_pylist()
    return sorted(table, key=lambda row: int(row["window_start"]))


def _quote(probability: float, multiple: float) -> tuple[float, float, float]:
    half_spread = SPREAD_BPS * multiple / 20_000.0
    mid = min(0.9999, max(0.0001, float(probability)))
    bid = max(0.0001, mid - half_spread)
    ask = min(0.9999, mid + half_spread)
    return bid, ask, mid


async def replay(rows: list[dict], multiple: float, out_dir: Path) -> dict:
    first = datetime.fromtimestamp(int(rows[0]["decision_ts"]), tz=UTC)
    clock = Clock(first)
    universe = [
        f"BTC5M:{row['window_start']}:{side}"
        for row in rows for side in ("UP", "DOWN")
    ]
    db = out_dir / f"btc5m-event-{uuid.uuid4().hex[:8]}.sqlite3"
    service = SimulationService(
        db, clock=clock, equity_poll_seconds=10**9,
        source_factories={"btc5m_event_replay": lambda config, _db: EventReplaySource()},
    )
    await service.start()
    run = await service.create_run(
        name=f"btc5m-event-kernel:{multiple}x",
        strategy_id="btc5m_event_replay", universe=universe,
        initial_capital=10_000.0,
        config={
            "position_fraction": 0.10, "fee_bps": 0.0,
            "mid_penalty_bps": 0.0, "allow_short": False,
            "cooldown_seconds": 0.0, "max_staleness_seconds": 600.0,
            "min_trade_notional": 0.0,
            "equity_interval_minutes": 1.0,
        },
    )
    run_id = str(run["run_id"])
    await service.start_run(run_id)
    traded = 0
    for row in rows:
        edge = float(row["model_probability"]) - float(row["market_probability"])
        if abs(edge) < EDGE_THRESHOLD:
            continue
        buy_up = edge >= EDGE_THRESHOLD
        probability = float(row["market_probability"] if buy_up else 1.0 - row["market_probability"])
        outcome = int(row["outcome_up"] if buy_up else 1 - row["outcome_up"])
        instrument = f"BTC5M:{row['window_start']}:{'UP' if buy_up else 'DOWN'}"
        entry_ts = datetime.fromtimestamp(int(row["decision_ts"]), tz=UTC)
        settle_ts = datetime.fromtimestamp(int(row["window_end"]), tz=UTC)
        bid, ask, mid = _quote(probability, multiple)
        for timestamp, signal_side, price in (
            (entry_ts, "buy", mid),
            (settle_ts, "sell", 0.9999 if outcome else 0.0001),
        ):
            clock.current = timestamp
            settle_bid = max(0.0001, price - 0.0001)
            settle_ask = min(0.9999, price + 0.0001)
            await service._dispatch("features.snapshots", {
                "market_id": instrument, "timestamp": timestamp,
                "mid_price": price if signal_side == "sell" else mid,
                "bid_price": (settle_bid if signal_side == "sell" else bid),
                "ask_price": (settle_ask if signal_side == "sell" else ask),
                "signal_side": signal_side,
                "signal_meta": {
                    "source": "btc5m_event_kernel_diagnostic",
                    "window_start": row["window_start"],
                    "raw_sha256": {
                        "gamma": row.get("gamma_raw_sha256"),
                        "clob": row.get("clob_raw_sha256"),
                        "okx": row.get("okx_raw_sha256"),
                    },
                    "execution_basis": "historical_probability_plus_fixed_spread_stress",
                },
            })
            await service._record_equity(service._active[run_id])
        traded += 1
    active = service._active.get(run_id)
    risk_rejections = active.risk_rejections if active is not None else None
    await service.stop_run(run_id)
    metrics = sim_metrics.compute_run_metrics(service.store, run_id)
    trades = len(service.store.list_trades(run_id))
    open_positions = len(service.store.list_positions(run_id))
    await service.stop()
    for suffix in ("", "-wal", "-shm"):
        db.with_name(db.name + suffix).unlink(missing_ok=True)
    return {"cost_multiple": multiple, "candidate_events": traded,
            "fills": trades, "risk_rejections": risk_rejections,
            "open_positions": open_positions, "metrics": metrics}


async def main_async() -> int:
    rows = load_rows()
    if len(rows) < 60:
        raise RuntimeError(f"insufficient v5 rows: {len(rows)}")
    out_dir = Path("data/.kernel_replay_btc5m_event")
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at": datetime.now(UTC).isoformat(), "real_data_only": True,
        "strategy": "btc5m_event_kernel_diagnostic",
        "tradable_evidence": False,
        "execution_basis": "historical midpoint plus fixed spread stress; not executable CLOB ask/depth",
        "dataset": str(DATASET), "rows": len(rows),
        "edge_threshold": EDGE_THRESHOLD, "spread_bps": SPREAD_BPS,
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
