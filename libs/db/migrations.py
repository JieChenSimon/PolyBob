"""Dialect-aware schema/migration definitions for the PolyBob fact store.

One source of truth for the DDL that both storage backends
(:mod:`libs.db.storage`) apply. Two dialects are supported:

* ``sqlite`` — the default, embedded, single-file engine. Types are chosen so
  the existing :mod:`libs.db.fact_store` schema stays byte-compatible.
* ``postgres`` — a PostgreSQL / TimescaleDB target. Time columns use
  ``TIMESTAMPTZ`` and the tick table is promoted to a Timescale *hypertable*
  (``create_hypertable``) so tick ingestion partitions by time automatically.

The SQLite DDL is fully importable and unit-testable with no server. The
Postgres DDL is returned as plain SQL strings so it can be inspected in tests
without a live database; the ``create_hypertable`` / ``CREATE EXTENSION`` calls
only run against a real TimescaleDB instance (see the live-gated tests).

References:
* TimescaleDB hypertables — ``SELECT create_hypertable('t', 'time')`` with a
  ``TIMESTAMPTZ`` partitioning column and a composite ``(asset_id, time DESC)``
  index for symbol+time lookups.
  https://docs.tigerdata.com/use-timescale/latest/hypertables/
"""

from __future__ import annotations

import sqlite3
from typing import Literal

Dialect = Literal["sqlite", "postgres"]

# Default Timescale chunk interval for tick data. High-frequency ticks favour
# shorter chunks than the 7-day default so per-chunk indexes stay in memory.
TICK_CHUNK_INTERVAL = "1 day"


# --- audit_events ---------------------------------------------------------
# Mirrors libs.db.fact_store SCHEMA_STATEMENTS for audit_events so both engines
# expose the same logical table.
_AUDIT_SQLITE = """
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'system',
    subject_type TEXT,
    subject_id TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
)
"""

_AUDIT_POSTGRES = """
CREATE TABLE IF NOT EXISTS audit_events (
    id BIGSERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'system',
    subject_type TEXT,
    subject_id TEXT,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


# --- market_ticks (time-series / hypertable target) ----------------------
# A dedicated tick table that demonstrates the Timescale hypertable path. On
# SQLite it is an ordinary table with a covering index; on Postgres it becomes a
# hypertable partitioned by ``time``.
_TICKS_SQLITE = """
CREATE TABLE IF NOT EXISTS market_ticks (
    time TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    price REAL NOT NULL,
    size REAL NOT NULL DEFAULT 0,
    side TEXT,
    source TEXT
)
"""

_TICKS_SQLITE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_market_ticks_asset_time
ON market_ticks (asset_id, time)
"""

_TICKS_POSTGRES = """
CREATE TABLE IF NOT EXISTS market_ticks (
    time TIMESTAMPTZ NOT NULL,
    asset_id TEXT NOT NULL,
    price DOUBLE PRECISION NOT NULL,
    size DOUBLE PRECISION NOT NULL DEFAULT 0,
    side TEXT,
    source TEXT
)
"""

_TICKS_POSTGRES_INDEX = """
CREATE INDEX IF NOT EXISTS idx_market_ticks_asset_time
ON market_ticks (asset_id, time DESC)
"""


def sqlite_ddl() -> tuple[str, ...]:
    """Return the ordered DDL statements for the SQLite dialect."""
    return (
        _AUDIT_SQLITE,
        _TICKS_SQLITE,
        _TICKS_SQLITE_INDEX,
    )


def postgres_ddl(*, timescale: bool = True) -> tuple[str, ...]:
    """Return ordered DDL statements for the PostgreSQL / TimescaleDB dialect.

    When ``timescale`` is true the tick table is promoted to a hypertable and a
    composite ``(asset_id, time DESC)`` index is created. ``create_hypertable``
    is called with ``if_not_exists`` and ``migrate_data`` so it is safe to run
    on an already-populated table.
    """
    statements: list[str] = []
    if timescale:
        statements.append("CREATE EXTENSION IF NOT EXISTS timescaledb")
    statements.append(_AUDIT_POSTGRES)
    statements.append(_TICKS_POSTGRES)
    if timescale:
        statements.append(
            "SELECT create_hypertable("
            "'market_ticks', 'time', "
            "chunk_time_interval => INTERVAL '%s', "
            "if_not_exists => TRUE, migrate_data => TRUE)" % TICK_CHUNK_INTERVAL
        )
    statements.append(_TICKS_POSTGRES_INDEX)
    return tuple(statements)


def ddl_for(dialect: Dialect, *, timescale: bool = True) -> tuple[str, ...]:
    """Return the DDL statements for ``dialect``."""
    if dialect == "sqlite":
        return sqlite_ddl()
    if dialect == "postgres":
        return postgres_ddl(timescale=timescale)
    raise ValueError(f"unknown dialect: {dialect!r}")


def apply_sqlite(connection: sqlite3.Connection) -> None:
    """Apply the SQLite DDL to an open connection (idempotent)."""
    for statement in sqlite_ddl():
        connection.execute(statement)
    connection.commit()


async def apply_postgres(connection, *, timescale: bool = True) -> None:
    """Apply the Postgres/Timescale DDL to an asyncpg connection (idempotent).

    Hypertable/extension creation is best-effort: on a plain PostgreSQL server
    without the Timescale extension the ``CREATE EXTENSION`` and
    ``create_hypertable`` calls raise, so they are attempted separately and the
    tick table still lands as an ordinary table.
    """
    # Core tables first so they exist even if Timescale features are missing.
    await connection.execute(_AUDIT_POSTGRES)
    await connection.execute(_TICKS_POSTGRES)
    if timescale:
        try:
            await connection.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
            await connection.execute(
                "SELECT create_hypertable("
                "'market_ticks', 'time', "
                f"chunk_time_interval => INTERVAL '{TICK_CHUNK_INTERVAL}', "
                "if_not_exists => TRUE, migrate_data => TRUE)"
            )
        except Exception:  # pragma: no cover - only exercised without Timescale
            # Plain PostgreSQL (no Timescale extension): degrade to a regular
            # table rather than failing the whole migration.
            pass
    await connection.execute(_TICKS_POSTGRES_INDEX)
