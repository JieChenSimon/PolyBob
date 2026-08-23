"""Durable strategy-instance records for the local workbench."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from libs.db import fact_store


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS strategy_instances (
    instance_id TEXT PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    name TEXT NOT NULL,
    config_json TEXT NOT NULL,
    risk_limits_json TEXT NOT NULL,
    environment TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_started_at TEXT,
    last_stopped_at TEXT
)
"""


class StrategyInstanceStore:
    """Persist control-plane records; never restore a running coroutine."""

    def __init__(self, db_path: str | Path | None = None):
        self._db_path = fact_store._resolve_db_path(db_path)

    def _connect(self):
        connection = fact_store.connect(self._db_path)
        connection.execute(_CREATE_TABLE)
        return connection

    def list(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM strategy_instances ORDER BY created_at, instance_id"
            ).fetchall()
        return [self._decode(row) for row in rows]

    def save(self, record: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO strategy_instances (
                    instance_id, strategy_id, name, config_json, risk_limits_json,
                    environment, created_at, updated_at, last_started_at, last_stopped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(instance_id) DO UPDATE SET
                    strategy_id = excluded.strategy_id,
                    name = excluded.name,
                    config_json = excluded.config_json,
                    risk_limits_json = excluded.risk_limits_json,
                    environment = excluded.environment,
                    updated_at = excluded.updated_at,
                    last_started_at = excluded.last_started_at,
                    last_stopped_at = excluded.last_stopped_at
                """,
                (
                    record["instance_id"], record["strategy_id"], record["name"],
                    json.dumps(record["config"], sort_keys=True, default=str),
                    json.dumps(record["risk_limits"], sort_keys=True, default=str),
                    record["environment"], record["created_at"], record["updated_at"],
                    record.get("last_started_at"), record.get("last_stopped_at"),
                ),
            )

    def delete(self, instance_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM strategy_instances WHERE instance_id = ?", (instance_id,))

    @staticmethod
    def _decode(row: Any) -> dict[str, Any]:
        def parse(value: str) -> dict[str, Any]:
            try:
                result = json.loads(value)
            except (TypeError, ValueError):
                return {}
            return result if isinstance(result, dict) else {}

        return {
            "instance_id": row["instance_id"],
            "strategy_id": row["strategy_id"],
            "name": row["name"],
            "config": parse(row["config_json"]),
            "risk_limits": parse(row["risk_limits_json"]),
            "environment": row["environment"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_started_at": row["last_started_at"],
            "last_stopped_at": row["last_stopped_at"],
        }


__all__ = ["StrategyInstanceStore"]
