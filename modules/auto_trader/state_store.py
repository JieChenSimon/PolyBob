"""Persistent state for the auto-trader (BTC demo) engine.

Standalone SQLite store following the :mod:`libs.db.strategy_state` pattern: it
owns its own ``auto_trader_state`` table (created lazily via
``CREATE TABLE IF NOT EXISTS``) and only *borrows* the connection helper from
:mod:`libs.db.fact_store` — it does not modify the fact-store schema.

Without this, the engine held ``capital``/``position``/``trades`` purely in
memory, so a process restart silently reset the reported PnL to the initial
capital. Persisting the authoritative state lets ``/api/trading/status`` and
``/api/trading/performance`` recover the true book after a restart.

All methods are synchronous; event-loop callers must wrap them in
``asyncio.to_thread``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from libs.db import fact_store

logger = structlog.get_logger()

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS auto_trader_state (
    engine_id TEXT PRIMARY KEY,
    initial_capital REAL NOT NULL,
    capital REAL NOT NULL,
    position REAL NOT NULL,
    entry_price REAL NOT NULL,
    trades_json TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL
)
"""


class AutoTraderStateStore:
    """Save/load the authoritative auto-trader book keyed by ``engine_id``."""

    def __init__(self, db_path: str | Path | None = None):
        self._db_path = fact_store._resolve_db_path(db_path)

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connect(self):
        connection = fact_store.connect(self._db_path)
        connection.execute(_CREATE_TABLE)
        return connection

    def save_state(self, engine_id: str, state: dict[str, Any]) -> None:
        """Upsert the full engine book for ``engine_id``."""
        trades_json = json.dumps(
            state.get("trades", []), separators=(",", ":"), default=str
        )
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO auto_trader_state
                    (engine_id, initial_capital, capital, position, entry_price,
                     trades_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(engine_id) DO UPDATE SET
                    initial_capital = excluded.initial_capital,
                    capital = excluded.capital,
                    position = excluded.position,
                    entry_price = excluded.entry_price,
                    trades_json = excluded.trades_json,
                    updated_at = excluded.updated_at
                """,
                (
                    engine_id,
                    float(state.get("initial_capital", 0.0)),
                    float(state.get("capital", 0.0)),
                    float(state.get("position", 0.0)),
                    float(state.get("entry_price", 0.0)),
                    trades_json,
                    now,
                ),
            )

    def load_state(self, engine_id: str) -> dict[str, Any] | None:
        """Return the stored book dict, or ``None`` when missing/corrupt.

        Never raises: a missing or unreadable DB degrades to ``None`` so the
        engine falls back to its constructor defaults instead of crashing.
        """
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT initial_capital, capital, position, entry_price, trades_json
                    FROM auto_trader_state WHERE engine_id = ?
                    """,
                    (engine_id,),
                ).fetchone()
        except Exception as exc:
            logger.warning(
                "auto_trader_state_load_failed",
                engine_id=engine_id,
                error=str(exc) or exc.__class__.__name__,
            )
            return None
        if row is None:
            return None
        try:
            trades = json.loads(row["trades_json"])
            if not isinstance(trades, list):
                trades = []
        except (TypeError, ValueError):
            logger.warning("auto_trader_state_trades_corrupt", engine_id=engine_id)
            trades = []
        return {
            "initial_capital": float(row["initial_capital"]),
            "capital": float(row["capital"]),
            "position": float(row["position"]),
            "entry_price": float(row["entry_price"]),
            "trades": trades,
        }
