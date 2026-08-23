"""Durable local job and feature-snapshot store for replayable research tasks."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from libs.db import fact_store


SCHEMA = (
    """CREATE TABLE IF NOT EXISTS task_runs (
        job_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE,
        kind TEXT NOT NULL, status TEXT NOT NULL, payload_json TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0, error TEXT, created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL, started_at TEXT, finished_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS feature_snapshots (
        snapshot_id TEXT PRIMARY KEY, instrument_id TEXT NOT NULL,
        observed_at TEXT NOT NULL, payload_json TEXT NOT NULL,
        source TEXT NOT NULL
    )""",
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class JobStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = fact_store._resolve_db_path(db_path)
        with fact_store.connect(self.db_path) as db:
            for statement in SCHEMA:
                db.execute(statement)
            db.commit()

    def enqueue(self, *, job_id: str, idempotency_key: str, kind: str,
                payload: dict[str, Any] | None = None) -> dict[str, Any]:
        now = _now()
        with fact_store.connect(self.db_path) as db:
            db.execute(
                "INSERT OR IGNORE INTO task_runs(job_id,idempotency_key,kind,status,payload_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                (job_id, idempotency_key, kind, "queued", json.dumps(payload or {}, sort_keys=True), now, now),
            )
            row = db.execute("SELECT * FROM task_runs WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        return dict(row)

    def transition(self, job_id: str, status: str, *, error: str | None = None) -> dict[str, Any]:
        allowed = {"queued", "running", "succeeded", "failed", "cancelled"}
        if status not in allowed:
            raise ValueError(f"unknown job status: {status}")
        now = _now()
        with fact_store.connect(self.db_path) as db:
            if status == "running":
                db.execute("UPDATE task_runs SET status=?, attempts=attempts+1, started_at=?, updated_at=? WHERE job_id=?", (status, now, now, job_id))
            else:
                db.execute("UPDATE task_runs SET status=?, error=?, finished_at=?, updated_at=? WHERE job_id=?", (status, error, now, now, job_id))
            row = db.execute("SELECT * FROM task_runs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return dict(row)

    def record_feature(self, *, snapshot_id: str, instrument_id: str, observed_at: str,
                       payload: dict[str, Any], source: str) -> bool:
        with fact_store.connect(self.db_path) as db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO feature_snapshots(snapshot_id,instrument_id,observed_at,payload_json,source) VALUES (?,?,?,?,?)",
                (snapshot_id, instrument_id, observed_at, json.dumps(payload, sort_keys=True), source),
            )
            return cursor.rowcount == 1

    def replay_feature(self, snapshot_id: str) -> dict[str, Any] | None:
        with fact_store.connect(self.db_path) as db:
            row = db.execute("SELECT * FROM feature_snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json"))
        return result
