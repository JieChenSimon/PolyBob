"""Persistent strategy state on top of the fact store SQLite file.

Standalone module: it owns its own ``strategy_state`` table (created lazily
via ``CREATE TABLE IF NOT EXISTS``) and only borrows the connection helper
from :mod:`libs.db.fact_store`. It deliberately does not touch the fact-store
schema statements or repositories, so it can evolve independently.

Usage::

    store = StrategyStateStore()          # default fact-store db path
    store.save_state("signal_fusion", {"weights": {...}})
    state = store.load_state("signal_fusion")  # {} when absent/corrupt
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from libs.db import fact_store

logger = structlog.get_logger()

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS strategy_state (
    strategy_id TEXT PRIMARY KEY,
    state_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
)
"""


class StrategyStateStore:
    """Save/load JSON strategy state keyed by strategy_id (SQLite WAL)."""

    def __init__(self, db_path: str | Path | None = None):
        self._db_path = fact_store._resolve_db_path(db_path)

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connect(self):
        connection = fact_store.connect(self._db_path)
        connection.execute(_CREATE_TABLE)
        return connection

    def save_state(self, strategy_id: str, state: Mapping[str, Any]) -> None:
        """Upsert the full state blob for one strategy."""
        payload = json.dumps(dict(state), sort_keys=True, separators=(",", ":"), default=str)
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO strategy_state (strategy_id, state_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(strategy_id) DO UPDATE SET
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (strategy_id, payload, now),
            )

    def load_state(self, strategy_id: str) -> dict[str, Any]:
        """Return the stored state dict, or {} when missing or corrupt.

        Corrupt/unparseable state never raises: the caller degrades to its
        built-in defaults instead of crashing on startup.
        """
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT state_json FROM strategy_state WHERE strategy_id = ?",
                    (strategy_id,),
                ).fetchone()
        except Exception as exc:
            logger.warning(
                "strategy_state_load_failed",
                strategy_id=strategy_id,
                error=str(exc) or exc.__class__.__name__,
            )
            return {}
        if row is None:
            return {}
        try:
            loaded = json.loads(row["state_json"])
        except (TypeError, ValueError):
            logger.warning("strategy_state_corrupt", strategy_id=strategy_id)
            return {}
        if not isinstance(loaded, dict):
            logger.warning("strategy_state_corrupt", strategy_id=strategy_id)
            return {}
        return loaded
