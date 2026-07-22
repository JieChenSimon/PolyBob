"""Minimal local SQLite fact store.

This module is intentionally standalone. It does not wire the fact store into
the API startup path, so workers can adopt it explicitly when ready.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Mapping
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


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open a SQLite connection for the local fact store."""
    path = _resolve_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


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
    """Append one audit event and return its row id."""
    path = _ensure_schema(db_path)
    timestamp = (created_at or datetime.now(UTC)).isoformat()
    payload_json = json.dumps(dict(payload or {}), sort_keys=True, separators=(",", ":"))

    with connect(path) as connection:
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
        return int(cursor.lastrowid)
