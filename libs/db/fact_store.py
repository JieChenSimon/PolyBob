"""Minimal local SQLite fact store.

This module is intentionally standalone. It does not wire the fact store into
the API startup path, so workers can adopt it explicitly when ready.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from libs.config import get_settings


SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS investment_cases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        case_key TEXT NOT NULL UNIQUE,
        title TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open',
        thesis TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        case_id INTEGER,
        decision_key TEXT NOT NULL UNIQUE,
        decision_type TEXT NOT NULL,
        rationale TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (case_id) REFERENCES investment_cases(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_key TEXT NOT NULL UNIQUE,
        case_id INTEGER,
        market_id TEXT,
        side TEXT NOT NULL,
        price REAL,
        quantity REAL,
        status TEXT NOT NULL DEFAULT 'created',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (case_id) REFERENCES investment_cases(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fill_key TEXT NOT NULL UNIQUE,
        order_id INTEGER,
        price REAL NOT NULL,
        quantity REAL NOT NULL,
        fee REAL NOT NULL DEFAULT 0,
        filled_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (order_id) REFERENCES orders(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ledger_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entry_key TEXT NOT NULL UNIQUE,
        case_id INTEGER,
        amount REAL NOT NULL,
        currency TEXT NOT NULL DEFAULT 'USD',
        entry_type TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (case_id) REFERENCES investment_cases(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS intents (
        intent_id TEXT PRIMARY KEY,
        payload_json TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'created',
        error TEXT,
        basket_id TEXT,
        idempotency_key TEXT UNIQUE,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS baskets (
        basket_id TEXT PRIMARY KEY,
        intent_id TEXT,
        status TEXT NOT NULL DEFAULT 'submitting',
        payload_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS basket_legs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        basket_id TEXT NOT NULL,
        leg_index INTEGER NOT NULL,
        payload_json TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'pending_submit',
        fill_json TEXT,
        UNIQUE (basket_id, leg_index),
        FOREIGN KEY (basket_id) REFERENCES baskets(basket_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS strategy_decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        decision_id TEXT NOT NULL UNIQUE,
        strategy_id TEXT NOT NULL,
        market_id TEXT,
        payload_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type TEXT NOT NULL,
        actor TEXT NOT NULL DEFAULT 'system',
        subject_type TEXT,
        subject_id TEXT,
        payload_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL
    )
    """,
)


def _resolve_db_path(db_path: str | Path | None = None) -> Path:
    return Path(db_path or get_settings().polybob_db_path).expanduser()


# Schema is initialized at most once per db path per process.
_initialized_paths: set[Path] = set()
_init_lock = threading.Lock()


def _ensure_schema(db_path: str | Path | None = None) -> Path:
    """Initialize the schema once per resolved db path per process."""
    path = _resolve_db_path(db_path).resolve()
    if path in _initialized_paths:
        return path
    with _init_lock:
        if path not in _initialized_paths:
            init_db(path)
            _initialized_paths.add(path)
    return path


def connect(
    db_path: str | Path | None = None, *, check_same_thread: bool = True
) -> sqlite3.Connection:
    """Open a SQLite connection for the local fact store.

    WAL journaling plus a 5s ``busy_timeout`` let readers run concurrently with
    the single writer and make brief write contention retry internally instead
    of raising ``SQLITE_BUSY`` immediately.
    """
    path = _resolve_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, check_same_thread=check_same_thread)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


# --- Persistent writer connection -----------------------------------------
# Audit appends are hot and previously opened (and tore down) a fresh SQLite
# connection on every call. Instead we keep ONE long-lived WAL connection per
# resolved db path, guarded by a lock so it is safe to share across the worker
# threads that services use (``asyncio.to_thread``). SQLite serialises writes to
# a single writer regardless, so a lock-guarded shared connection matches the
# engine's model while removing per-write connect/close churn.
_writer_connections: dict[Path, sqlite3.Connection] = {}
_writer_locks: dict[Path, threading.Lock] = {}
_writer_registry_lock = threading.Lock()


def _get_writer(db_path: str | Path | None = None) -> tuple[sqlite3.Connection, threading.Lock]:
    """Return the shared writer connection and its lock for ``db_path``.

    The schema is migrated once (via :func:`_ensure_schema`) before the
    connection is created, so no per-write schema initialisation happens.
    """
    path = _ensure_schema(db_path)
    connection = _writer_connections.get(path)
    if connection is not None:
        return connection, _writer_locks[path]
    with _writer_registry_lock:
        connection = _writer_connections.get(path)
        if connection is None:
            connection = connect(path, check_same_thread=False)
            _writer_connections[path] = connection
            _writer_locks[path] = threading.Lock()
        return connection, _writer_locks[path]


def close_writer_connections(db_path: str | Path | None = None) -> None:
    """Close persistent writer connection(s).

    With no argument every cached writer connection is closed (useful at process
    shutdown or between tests). With a path, only that connection is closed.
    """
    with _writer_registry_lock:
        if db_path is None:
            paths = list(_writer_connections)
        else:
            paths = [_resolve_db_path(db_path).resolve()]
        for path in paths:
            connection = _writer_connections.pop(path, None)
            _writer_locks.pop(path, None)
            if connection is not None:
                try:
                    connection.close()
                except sqlite3.Error:
                    pass


def init_db(db_path: str | Path | None = None) -> Path:
    """Create the minimal fact-store schema if it does not already exist."""
    path = _resolve_db_path(db_path)
    with connect(path) as connection:
        for statement in SCHEMA_STATEMENTS:
            connection.execute(statement)
    return path


def bootstrap(db_path: str | Path | None = None) -> Path:
    """Alias for init_db used by callers that prefer bootstrap wording."""
    return init_db(db_path)


def append_audit_event(
    event_type: str,
    *,
    actor: str = "system",
    subject_type: str | None = None,
    subject_id: str | None = None,
    payload: Mapping[str, Any] | None = None,
    db_path: str | Path | None = None,
    created_at: datetime | None = None,
) -> int:
    """Append one audit event and return its row id.

    Uses the shared persistent WAL writer connection: the schema is migrated
    once per path (not per write) and no connection is opened/closed per call.
    """
    timestamp = (created_at or datetime.now(UTC)).isoformat()
    payload_json = json.dumps(dict(payload or {}), sort_keys=True, separators=(",", ":"))

    connection, lock = _get_writer(db_path)
    with lock:
        cursor = connection.execute(
            """
            INSERT INTO audit_events (
                event_type,
                actor,
                subject_type,
                subject_id,
                payload_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (event_type, actor, subject_type, subject_id, payload_json, timestamp),
        )
        connection.commit()
        return int(cursor.lastrowid)


def append_audit_events(
    events: Iterable[Mapping[str, Any]],
    *,
    db_path: str | Path | None = None,
) -> int:
    """Append many audit events in one transaction; returns the count written.

    Each mapping accepts the same keys as :func:`append_audit_event`
    (``event_type`` required; ``actor``/``subject_type``/``subject_id``/
    ``payload``/``created_at`` optional). Batching amortises the commit cost
    across a burst of events.
    """
    rows: list[tuple[Any, ...]] = []
    for event in events:
        created = event.get("created_at")
        if isinstance(created, datetime):
            timestamp = created.isoformat()
        else:
            timestamp = str(created) if created else datetime.now(UTC).isoformat()
        rows.append(
            (
                event["event_type"],
                event.get("actor", "system"),
                event.get("subject_type"),
                event.get("subject_id"),
                json.dumps(dict(event.get("payload") or {}), sort_keys=True, separators=(",", ":")),
                timestamp,
            )
        )
    if not rows:
        return 0

    connection, lock = _get_writer(db_path)
    with lock:
        connection.executemany(
            """
            INSERT INTO audit_events (
                event_type, actor, subject_type, subject_id, payload_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        connection.commit()
    return len(rows)
