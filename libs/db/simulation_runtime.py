"""Durable operator controls for the paper-simulation runtime.

The runtime switch is deliberately separate from environment configuration:
environment variables provide the deployment default, while this small
SQLite record lets the Paper Lab be operated from the UI and survive a
restart.  No setting in this module grants live execution permission.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from libs.db import fact_store


class SimulationRuntimeStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = fact_store._resolve_db_path(db_path)
        with fact_store.connect(self.db_path) as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS simulation_runtime (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    enabled INTEGER NOT NULL,
                    auto_run INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            db.commit()

    def read(self) -> dict[str, bool] | None:
        with fact_store.connect(self.db_path) as db:
            row = db.execute(
                "SELECT enabled, auto_run FROM simulation_runtime WHERE id=1"
            ).fetchone()
        if row is None:
            return None
        return {"enabled": bool(row[0]), "auto_run": bool(row[1])}

    def write(self, *, enabled: bool, auto_run: bool) -> dict[str, bool]:
        now = datetime.now(UTC).isoformat()
        with fact_store.connect(self.db_path) as db:
            db.execute(
                """INSERT INTO simulation_runtime(id, enabled, auto_run, updated_at)
                   VALUES (1, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET enabled=excluded.enabled,
                   auto_run=excluded.auto_run, updated_at=excluded.updated_at""",
                (int(enabled), int(auto_run), now),
            )
            db.commit()
        return {"enabled": enabled, "auto_run": auto_run}
