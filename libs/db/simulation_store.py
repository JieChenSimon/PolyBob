"""Persistent storage for paper-trading simulation runs.

Standalone module following the :mod:`libs.db.strategy_state` pattern: it owns
its own tables (created lazily via ``CREATE TABLE IF NOT EXISTS`` on connect)
and only borrows the connection helper from :mod:`libs.db.fact_store`, so it
can evolve independently of the fact-store schema statements.

Tables:

- ``sim_runs``          one row per simulation run (capital, status, config)
- ``sim_positions``     current open position per (run, instrument), avg-price
- ``sim_trades``        append-only fills; ``realized_pnl`` is NULL for trades
                        that only open/extend a position and set for trades
                        that close (part of) one; quote provenance is stored
                        beside each fill so missing depth is explicit
- ``sim_equity_points`` periodic equity snapshots (equity curve source)

All methods are synchronous; event-loop callers must wrap them in
``asyncio.to_thread`` (the repositories.py convention).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from libs.db import fact_store

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS sim_runs (
        run_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        strategy_id TEXT NOT NULL,
        universe_json TEXT NOT NULL DEFAULT '[]',
        initial_capital REAL NOT NULL,
        cash REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'paused',
        config_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sim_positions (
        run_id TEXT NOT NULL,
        instrument_id TEXT NOT NULL,
        size REAL NOT NULL,
        avg_price REAL NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (run_id, instrument_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sim_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        instrument_id TEXT NOT NULL,
        side TEXT NOT NULL,
        size REAL NOT NULL,
        price REAL NOT NULL,
        fee REAL NOT NULL DEFAULT 0,
        slippage REAL NOT NULL DEFAULT 0,
        signal_meta_json TEXT NOT NULL DEFAULT '{}',
        realized_pnl REAL,
        executed_at TEXT NOT NULL,
        quote_bid REAL,
        quote_ask REAL,
        bid_depth REAL,
        ask_depth REAL,
        quote_timestamp TEXT,
        quote_source TEXT NOT NULL DEFAULT 'unknown',
        quote_provenance_json TEXT NOT NULL DEFAULT '{}',
        quote_quality TEXT NOT NULL DEFAULT 'unknown'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sim_equity_points (
        run_id TEXT NOT NULL,
        ts TEXT NOT NULL,
        equity REAL NOT NULL,
        cash REAL NOT NULL,
        gross_exposure REAL NOT NULL DEFAULT 0,
        degraded INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (run_id, ts)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sim_trades_run ON sim_trades(run_id, id)",
    """
    CREATE TABLE IF NOT EXISTS sim_funding (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        instrument_id TEXT NOT NULL,
        rate REAL NOT NULL,
        notional REAL NOT NULL,
        pnl REAL NOT NULL,
        source TEXT NOT NULL DEFAULT 'market_snapshot',
        applied_at TEXT NOT NULL,
        UNIQUE (run_id, instrument_id, applied_at)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sim_funding_run ON sim_funding(run_id, id)",
    """
    CREATE TABLE IF NOT EXISTS sim_settlements (
        settlement_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        market_id TEXT NOT NULL,
        instrument_id TEXT NOT NULL,
        quantity REAL NOT NULL,
        payout_per_token REAL NOT NULL CHECK (payout_per_token IN (0.0, 1.0)),
        cash_delta REAL NOT NULL,
        realized_pnl REAL NOT NULL,
        settled_at TEXT NOT NULL,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sim_settlements_run ON sim_settlements(run_id, settled_at)",
)

RUN_STATUSES = ("running", "paused", "stopped")


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _dump_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _load_json(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class SimRunRecord:
    run_id: str
    name: str
    strategy_id: str
    universe: list[str]
    initial_capital: float
    cash: float
    status: str
    config: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "name": self.name,
            "strategy_id": self.strategy_id,
            "universe": list(self.universe),
            "initial_capital": self.initial_capital,
            "cash": self.cash,
            "status": self.status,
            "config": dict(self.config),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class SimPositionRecord:
    run_id: str
    instrument_id: str
    size: float
    avg_price: float
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "instrument_id": self.instrument_id,
            "size": self.size,
            "avg_price": self.avg_price,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class SimTradeRecord:
    trade_id: int
    run_id: str
    instrument_id: str
    side: str
    size: float
    price: float
    fee: float
    slippage: float
    signal_meta: dict[str, Any]
    realized_pnl: float | None
    executed_at: str
    quote_bid: float | None = None
    quote_ask: float | None = None
    bid_depth: float | None = None
    ask_depth: float | None = None
    quote_timestamp: str | None = None
    quote_source: str = "unknown"
    quote_provenance: dict[str, Any] = field(default_factory=dict)
    quote_quality: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "run_id": self.run_id,
            "instrument_id": self.instrument_id,
            "side": self.side,
            "size": self.size,
            "price": self.price,
            "fee": self.fee,
            "slippage": self.slippage,
            "signal_meta": dict(self.signal_meta),
            "realized_pnl": self.realized_pnl,
            "executed_at": self.executed_at,
            "quote_bid": self.quote_bid,
            "quote_ask": self.quote_ask,
            "bid_depth": self.bid_depth,
            "ask_depth": self.ask_depth,
            "quote_timestamp": self.quote_timestamp,
            "quote_source": self.quote_source,
            "quote_provenance": dict(self.quote_provenance),
            "quote_quality": self.quote_quality,
        }


@dataclass(frozen=True)
class SimSettlementRecord:
    settlement_id: str
    run_id: str
    market_id: str
    instrument_id: str
    quantity: float
    payout_per_token: float
    cash_delta: float
    realized_pnl: float
    settled_at: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "settlement_id": self.settlement_id,
            "run_id": self.run_id,
            "market_id": self.market_id,
            "instrument_id": self.instrument_id,
            "quantity": self.quantity,
            "payout_per_token": self.payout_per_token,
            "cash_delta": self.cash_delta,
            "realized_pnl": self.realized_pnl,
            "settled_at": self.settled_at,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SimEquityPointRecord:
    run_id: str
    ts: str
    equity: float
    cash: float
    gross_exposure: float
    # True when a position had to be valued at something other than a fresh
    # mark. The curve carries its own provenance so metrics can refuse to
    # summarise it rather than quietly reporting a number built on entry prices.
    degraded: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "ts": self.ts,
            "equity": self.equity,
            "cash": self.cash,
            "gross_exposure": self.gross_exposure,
        }


class SimulationStore:
    """SQLite (WAL) persistence for simulation runs/positions/trades/equity."""

    def __init__(self, db_path: str | Path | None = None):
        self._db_path = fact_store._resolve_db_path(db_path)

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        connection = fact_store.connect(self._db_path)
        for statement in _SCHEMA_STATEMENTS:
            connection.execute(statement)
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(sim_trades)").fetchall()
        }
        migrations = (
            ("quote_bid", "REAL"),
            ("quote_ask", "REAL"),
            ("bid_depth", "REAL"),
            ("ask_depth", "REAL"),
            ("quote_timestamp", "TEXT"),
            ("quote_source", "TEXT NOT NULL DEFAULT 'unknown'"),
            ("quote_provenance_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("quote_quality", "TEXT NOT NULL DEFAULT 'unknown'"),
        )
        for name, definition in migrations:
            if name not in columns:
                connection.execute(
                    f"ALTER TABLE sim_trades ADD COLUMN {name} {definition}"
                )
        return connection

    # ------------------------------------------------------------------ runs

    def save_run(self, record: SimRunRecord) -> None:
        now = _utcnow_iso()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sim_runs (
                    run_id, name, strategy_id, universe_json, initial_capital,
                    cash, status, config_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    name = excluded.name,
                    strategy_id = excluded.strategy_id,
                    universe_json = excluded.universe_json,
                    initial_capital = excluded.initial_capital,
                    cash = excluded.cash,
                    status = excluded.status,
                    config_json = excluded.config_json,
                    updated_at = excluded.updated_at
                """,
                (
                    record.run_id,
                    record.name,
                    record.strategy_id,
                    _dump_json(list(record.universe)),
                    float(record.initial_capital),
                    float(record.cash),
                    record.status,
                    _dump_json(dict(record.config)),
                    record.created_at or now,
                    now,
                ),
            )

    def update_run(
        self,
        run_id: str,
        *,
        status: str | None = None,
        cash: float | None = None,
        config: Mapping[str, Any] | None = None,
    ) -> None:
        sets: list[str] = ["updated_at = ?"]
        params: list[Any] = [_utcnow_iso()]
        if status is not None:
            sets.append("status = ?")
            params.append(status)
        if cash is not None:
            sets.append("cash = ?")
            params.append(float(cash))
        if config is not None:
            sets.append("config_json = ?")
            params.append(_dump_json(dict(config)))
        params.append(run_id)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE sim_runs SET {', '.join(sets)} WHERE run_id = ?", params
            )

    def get_run(self, run_id: str) -> SimRunRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sim_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return self._run_record(row) if row else None

    def list_runs(self, *, status: str | None = None) -> list[SimRunRecord]:
        query = "SELECT * FROM sim_runs"
        params: list[Any] = []
        if status is not None:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY created_at"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._run_record(row) for row in rows]

    @staticmethod
    def _run_record(row: sqlite3.Row) -> SimRunRecord:
        universe = _load_json(row["universe_json"], [])
        config = _load_json(row["config_json"], {})
        return SimRunRecord(
            run_id=row["run_id"],
            name=row["name"],
            strategy_id=row["strategy_id"],
            universe=[str(item) for item in universe] if isinstance(universe, list) else [],
            initial_capital=float(row["initial_capital"]),
            cash=float(row["cash"]),
            status=row["status"],
            config=config if isinstance(config, dict) else {},
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # ------------------------------------------------------------- positions

    def upsert_position(
        self, run_id: str, instrument_id: str, size: float, avg_price: float
    ) -> None:
        with self._connect() as connection:
            if abs(size) < 1e-12:
                connection.execute(
                    "DELETE FROM sim_positions WHERE run_id = ? AND instrument_id = ?",
                    (run_id, instrument_id),
                )
                return
            connection.execute(
                """
                INSERT INTO sim_positions (run_id, instrument_id, size, avg_price, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_id, instrument_id) DO UPDATE SET
                    size = excluded.size,
                    avg_price = excluded.avg_price,
                    updated_at = excluded.updated_at
                """,
                (run_id, instrument_id, float(size), float(avg_price), _utcnow_iso()),
            )

    def list_positions(self, run_id: str) -> list[SimPositionRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM sim_positions WHERE run_id = ? ORDER BY instrument_id",
                (run_id,),
            ).fetchall()
        return [
            SimPositionRecord(
                run_id=row["run_id"],
                instrument_id=row["instrument_id"],
                size=float(row["size"]),
                avg_price=float(row["avg_price"]),
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    # ---------------------------------------------------------------- trades

    def append_trade(
        self,
        run_id: str,
        *,
        instrument_id: str,
        side: str,
        size: float,
        price: float,
        fee: float,
        slippage: float,
        signal_meta: Mapping[str, Any] | None = None,
        realized_pnl: float | None = None,
        executed_at: str | None = None,
        quote_bid: float | None = None,
        quote_ask: float | None = None,
        bid_depth: float | None = None,
        ask_depth: float | None = None,
        quote_timestamp: str | None = None,
        quote_source: str = "unknown",
        quote_provenance: Mapping[str, Any] | None = None,
        quote_quality: str = "unknown",
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO sim_trades (
                    run_id, instrument_id, side, size, price, fee, slippage,
                    signal_meta_json, realized_pnl, executed_at, quote_bid,
                    quote_ask, bid_depth, ask_depth, quote_timestamp,
                    quote_source, quote_provenance_json, quote_quality
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    instrument_id,
                    side,
                    float(size),
                    float(price),
                    float(fee),
                    float(slippage),
                    _dump_json(dict(signal_meta or {})),
                    realized_pnl,
                    executed_at or _utcnow_iso(),
                    quote_bid,
                    quote_ask,
                    bid_depth,
                    ask_depth,
                    quote_timestamp,
                    str(quote_source or "unknown"),
                    _dump_json(dict(quote_provenance or {})),
                    str(quote_quality or "unknown"),
                ),
            )
            return int(cursor.lastrowid)

    def list_trades(
        self,
        run_id: str,
        *,
        limit: int | None = None,
        after_id: int | None = None,
    ) -> list[SimTradeRecord]:
        query = "SELECT * FROM sim_trades WHERE run_id = ?"
        params: list[Any] = [run_id]
        if after_id is not None:
            query += " AND id > ?"
            params.append(int(after_id))
        query += " ORDER BY id"
        if limit is not None:
            # Latest ``limit`` trades, still in chronological order.
            query = f"SELECT * FROM ({query.replace('ORDER BY id', 'ORDER BY id DESC')} LIMIT ?) ORDER BY id"
            params.append(int(limit))
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._trade_record(row) for row in rows]

    def append_funding(
        self, run_id: str, *, instrument_id: str, rate: float, notional: float,
        pnl: float, applied_at: str, source: str = "market_snapshot",
    ) -> bool:
        """Apply one funding interval exactly once; return whether it was new."""
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO sim_funding
                    (run_id, instrument_id, rate, notional, pnl, source, applied_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, instrument_id, float(rate), float(notional), float(pnl), source, applied_at),
            )
            return cursor.rowcount == 1

    def apply_settlement(
        self,
        run_id: str,
        *,
        settlement_id: str,
        market_id: str,
        instrument_id: str,
        quantity: float,
        payout_per_token: float,
        settled_at: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> tuple[SimSettlementRecord, bool]:
        """Atomically record settlement and update run cash/position projections."""
        if payout_per_token not in (0.0, 1.0):
            raise ValueError("payout_per_token must be exactly 0 or 1")
        if quantity <= 0:
            raise ValueError("settlement quantity must be positive")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM sim_settlements WHERE settlement_id = ?", (settlement_id,)
            ).fetchone()
            if existing is not None:
                record = self._settlement_record(existing)
                if (
                    record.run_id != run_id
                    or record.market_id != market_id
                    or record.instrument_id != instrument_id
                    or abs(record.quantity - float(quantity)) > 1e-12
                    or abs(record.payout_per_token - float(payout_per_token)) > 1e-12
                ):
                    raise ValueError("settlement_id was reused with different economic content")
                connection.rollback()
                return record, True

            position = connection.execute(
                "SELECT * FROM sim_positions WHERE run_id = ? AND instrument_id = ?",
                (run_id, instrument_id),
            ).fetchone()
            current_size = float(position["size"]) if position else 0.0
            if current_size <= 0 or quantity > current_size + 1e-12:
                raise ValueError(
                    f"settlement quantity {quantity} exceeds long position {current_size}"
                )
            current_avg = float(position["avg_price"])
            cash_delta = float(quantity) * float(payout_per_token)
            realized_pnl = float(quantity) * (float(payout_per_token) - current_avg)
            new_size = current_size - float(quantity)
            now = _utcnow_iso()
            connection.execute(
                """
                INSERT INTO sim_settlements (
                    settlement_id, run_id, market_id, instrument_id, quantity,
                    payout_per_token, cash_delta, realized_pnl, settled_at,
                    metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    settlement_id, run_id, market_id, instrument_id, float(quantity),
                    float(payout_per_token), cash_delta, realized_pnl, settled_at,
                    _dump_json(dict(metadata or {})), now,
                ),
            )
            connection.execute(
                "UPDATE sim_runs SET cash = cash + ?, updated_at = ? WHERE run_id = ?",
                (cash_delta, now, run_id),
            )
            if abs(new_size) < 1e-12:
                connection.execute(
                    "DELETE FROM sim_positions WHERE run_id = ? AND instrument_id = ?",
                    (run_id, instrument_id),
                )
            else:
                connection.execute(
                    "UPDATE sim_positions SET size = ?, updated_at = ? "
                    "WHERE run_id = ? AND instrument_id = ?",
                    (new_size, now, run_id, instrument_id),
                )
            row = connection.execute(
                "SELECT * FROM sim_settlements WHERE settlement_id = ?", (settlement_id,)
            ).fetchone()
            connection.commit()
        return self._settlement_record(row), False

    def list_settlements(self, run_id: str) -> list[SimSettlementRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM sim_settlements WHERE run_id = ? "
                "ORDER BY settled_at, settlement_id",
                (run_id,),
            ).fetchall()
        return [self._settlement_record(row) for row in rows]

    def total_funding(self, run_id: str) -> float:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(SUM(pnl), 0) AS pnl FROM sim_funding WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return float(row["pnl"])

    def count_funding(self, run_id: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM sim_funding WHERE run_id = ?", (run_id,)
            ).fetchone()
        return int(row["count"])

    @staticmethod
    def _trade_record(row: sqlite3.Row) -> SimTradeRecord:
        meta = _load_json(row["signal_meta_json"], {})
        return SimTradeRecord(
            trade_id=int(row["id"]),
            run_id=row["run_id"],
            instrument_id=row["instrument_id"],
            side=row["side"],
            size=float(row["size"]),
            price=float(row["price"]),
            fee=float(row["fee"]),
            slippage=float(row["slippage"]),
            signal_meta=meta if isinstance(meta, dict) else {},
            realized_pnl=(
                float(row["realized_pnl"]) if row["realized_pnl"] is not None else None
            ),
            executed_at=row["executed_at"],
            quote_bid=(float(row["quote_bid"]) if row["quote_bid"] is not None else None),
            quote_ask=(float(row["quote_ask"]) if row["quote_ask"] is not None else None),
            bid_depth=(float(row["bid_depth"]) if row["bid_depth"] is not None else None),
            ask_depth=(float(row["ask_depth"]) if row["ask_depth"] is not None else None),
            quote_timestamp=row["quote_timestamp"],
            quote_source=row["quote_source"] or "unknown",
            quote_provenance=_load_json(row["quote_provenance_json"], {}) or {},
            quote_quality=row["quote_quality"] or "unknown",
        )

    @staticmethod
    def _settlement_record(row: sqlite3.Row) -> SimSettlementRecord:
        metadata = _load_json(row["metadata_json"], {})
        return SimSettlementRecord(
            settlement_id=row["settlement_id"],
            run_id=row["run_id"],
            market_id=row["market_id"],
            instrument_id=row["instrument_id"],
            quantity=float(row["quantity"]),
            payout_per_token=float(row["payout_per_token"]),
            cash_delta=float(row["cash_delta"]),
            realized_pnl=float(row["realized_pnl"]),
            settled_at=row["settled_at"],
            metadata=metadata if isinstance(metadata, dict) else {},
        )

    # ---------------------------------------------------------------- equity

    def append_equity_point(
        self,
        run_id: str,
        *,
        equity: float,
        cash: float,
        gross_exposure: float,
        ts: str | None = None,
        degraded: bool = False,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO sim_equity_points
                    (run_id, ts, equity, cash, gross_exposure, degraded)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    ts or _utcnow_iso(),
                    float(equity),
                    float(cash),
                    float(gross_exposure),
                    1 if degraded else 0,
                ),
            )

    def list_equity_points(self, run_id: str) -> list[SimEquityPointRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM sim_equity_points WHERE run_id = ? ORDER BY ts",
                (run_id,),
            ).fetchall()
        return [
            SimEquityPointRecord(
                run_id=row["run_id"],
                ts=row["ts"],
                equity=float(row["equity"]),
                cash=float(row["cash"]),
                gross_exposure=float(row["gross_exposure"]),
                degraded=bool(row["degraded"]) if "degraded" in row.keys() else False,
            )
            for row in rows
        ]


__all__ = [
    "RUN_STATUSES",
    "SimEquityPointRecord",
    "SimPositionRecord",
    "SimRunRecord",
    "SimTradeRecord",
    "SimulationStore",
]
