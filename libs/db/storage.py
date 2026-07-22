"""One storage interface with pluggable backends.

Audit / history / tick writes go through a single :class:`StorageBackend`
async interface so the persistence engine can be swapped by configuration
without touching call sites:

* ``sqlite`` (default, and the fallback) — :class:`SQLiteStorageBackend`, a thin
  async wrapper over the existing synchronous :mod:`libs.db.fact_store` code,
  offloaded to a worker thread. No server required, so every existing test and
  local run keeps working unchanged.
* ``postgres`` / ``timescale`` — :class:`PostgresStorageBackend`, an asyncpg
  adapter that applies the Postgres/Timescale DDL (incl. hypertable creation)
  from :mod:`libs.db.migrations`.

Selection is driven by ``POLYBOB_STORAGE_BACKEND`` (default ``sqlite``) and the
``DATABASE_URL`` setting. SQLite stays the default *and* the fallback: if a
Postgres backend is requested but the server is unreachable,
:func:`open_storage_backend` degrades to SQLite instead of failing startup.

The interface is async because asyncpg is natively async; the SQLite backend
runs its blocking calls via ``asyncio.to_thread`` so callers see one uniform
awaitable API regardless of the engine underneath.

References:
* Repository/adapter pattern for swappable persistence backends.
* SQLite WAL + ``busy_timeout`` for concurrent readers/single writer.
* TimescaleDB hypertables for tick/time-series ingestion.
"""

from __future__ import annotations

import abc
import asyncio
import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from libs.config import get_settings
from libs.db import fact_store, migrations

logger = structlog.get_logger()


BackendName = str

_SUPPORTED_BACKENDS = {"sqlite", "postgres", "timescale"}


def resolve_backend_name(explicit: str | None = None) -> str:
    """Resolve the configured storage backend name.

    Order of precedence: explicit argument, ``POLYBOB_STORAGE_BACKEND`` env var,
    then the SQLite default. ``timescale`` is treated as ``postgres`` + Timescale
    features enabled.
    """
    name = (explicit or os.getenv("POLYBOB_STORAGE_BACKEND", "sqlite")).strip().lower()
    if name not in _SUPPORTED_BACKENDS:
        raise ValueError(
            f"POLYBOB_STORAGE_BACKEND must be one of {sorted(_SUPPORTED_BACKENDS)}, got {name!r}"
        )
    return name


def asyncpg_dsn(database_url: str) -> str:
    """Normalise a SQLAlchemy-style URL to an asyncpg DSN.

    asyncpg does not understand the ``+asyncpg`` driver suffix that the settings
    default carries (``postgresql+asyncpg://...``).
    """
    return database_url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgres+asyncpg://", "postgresql://"
    )


class StorageBackend(abc.ABC):
    """Async persistence interface shared by all backends."""

    #: Human-readable backend identifier (e.g. ``"sqlite"`` / ``"timescale"``).
    backend_name: str = "abstract"

    @abc.abstractmethod
    async def initialize(self) -> None:
        """Create/upgrade the schema. Idempotent."""

    @abc.abstractmethod
    async def append_audit_event(
        self,
        event_type: str,
        *,
        actor: str = "system",
        subject_type: str | None = None,
        subject_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> int | None:
        """Append one audit event; returns its row id when available."""

    @abc.abstractmethod
    async def fetch_audit_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return the most recent audit events (newest first)."""

    @abc.abstractmethod
    async def record_tick(
        self,
        *,
        asset_id: str,
        price: float,
        size: float = 0.0,
        side: str | None = None,
        source: str | None = None,
        time: datetime | None = None,
    ) -> None:
        """Append one market tick to the time-series table."""

    @abc.abstractmethod
    async def fetch_ticks(self, asset_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent ticks for ``asset_id`` (newest first)."""

    @abc.abstractmethod
    async def health_check(self) -> bool:
        """Return True when the backend is reachable and usable."""

    async def close(self) -> None:  # pragma: no cover - trivial default
        """Release any held resources. Safe to call multiple times."""


class SQLiteStorageBackend(StorageBackend):
    """Default backend: async facade over the synchronous SQLite fact store."""

    backend_name = "sqlite"

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = fact_store._resolve_db_path(db_path)

    @property
    def db_path(self) -> Path:
        return self._db_path

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)

    def _initialize_sync(self) -> None:
        # fact_store owns the core audit schema; add the tick table on top.
        fact_store._ensure_schema(self._db_path)
        with fact_store.connect(self._db_path) as connection:
            migrations.apply_sqlite(connection)

    async def append_audit_event(
        self,
        event_type: str,
        *,
        actor: str = "system",
        subject_type: str | None = None,
        subject_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> int | None:
        return await asyncio.to_thread(
            fact_store.append_audit_event,
            event_type,
            actor=actor,
            subject_type=subject_type,
            subject_id=subject_id,
            payload=payload,
            db_path=self._db_path,
            created_at=created_at,
        )

    async def fetch_audit_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._fetch_audit_events_sync, limit)

    def _fetch_audit_events_sync(self, limit: int) -> list[dict[str, Any]]:
        fact_store._ensure_schema(self._db_path)
        with fact_store.connect(self._db_path) as connection:
            rows = connection.execute(
                "SELECT * FROM audit_events ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [dict(row) for row in rows]

    async def record_tick(
        self,
        *,
        asset_id: str,
        price: float,
        size: float = 0.0,
        side: str | None = None,
        source: str | None = None,
        time: datetime | None = None,
    ) -> None:
        await asyncio.to_thread(
            self._record_tick_sync, asset_id, price, size, side, source, time
        )

    def _record_tick_sync(
        self,
        asset_id: str,
        price: float,
        size: float,
        side: str | None,
        source: str | None,
        time: datetime | None,
    ) -> None:
        self._initialize_sync()
        timestamp = (time or datetime.now(UTC)).isoformat()
        with fact_store.connect(self._db_path) as connection:
            connection.execute(
                "INSERT INTO market_ticks (time, asset_id, price, size, side, source) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (timestamp, asset_id, float(price), float(size), side, source),
            )

    async def fetch_ticks(self, asset_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._fetch_ticks_sync, asset_id, limit)

    def _fetch_ticks_sync(self, asset_id: str, limit: int) -> list[dict[str, Any]]:
        self._initialize_sync()
        with fact_store.connect(self._db_path) as connection:
            rows = connection.execute(
                "SELECT * FROM market_ticks WHERE asset_id = ? ORDER BY time DESC LIMIT ?",
                (asset_id, int(limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    async def health_check(self) -> bool:
        try:
            await asyncio.to_thread(self._initialize_sync)
            return True
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("sqlite_health_check_failed", error=str(exc))
            return False

    async def close(self) -> None:
        await asyncio.to_thread(fact_store.close_writer_connections, self._db_path)


class PostgresStorageBackend(StorageBackend):
    """PostgreSQL / TimescaleDB backend (asyncpg).

    Importing this class never touches the network; a connection pool is only
    created in :meth:`initialize`. When ``timescale`` is true, the tick table is
    promoted to a hypertable via :func:`libs.db.migrations.apply_postgres`.
    """

    def __init__(self, dsn: str, *, timescale: bool = True) -> None:
        self._dsn = asyncpg_dsn(dsn)
        self._timescale = timescale
        self.backend_name = "timescale" if timescale else "postgres"
        self._pool: Any | None = None

    async def initialize(self) -> None:
        import asyncpg  # local import so module import needs no live driver setup

        if self._pool is None:
            self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=5)
        async with self._pool.acquire() as connection:
            await migrations.apply_postgres(connection, timescale=self._timescale)

    def _require_pool(self):
        if self._pool is None:
            raise RuntimeError("PostgresStorageBackend.initialize() must be awaited first")
        return self._pool

    async def append_audit_event(
        self,
        event_type: str,
        *,
        actor: str = "system",
        subject_type: str | None = None,
        subject_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> int | None:
        payload_json = json.dumps(dict(payload or {}), sort_keys=True, separators=(",", ":"))
        timestamp = created_at or datetime.now(UTC)
        async with self._require_pool().acquire() as connection:
            row = await connection.fetchrow(
                "INSERT INTO audit_events "
                "(event_type, actor, subject_type, subject_id, payload_json, created_at) "
                "VALUES ($1, $2, $3, $4, $5::jsonb, $6) RETURNING id",
                event_type,
                actor,
                subject_type,
                subject_id,
                payload_json,
                timestamp,
            )
        return int(row["id"]) if row else None

    async def fetch_audit_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        async with self._require_pool().acquire() as connection:
            rows = await connection.fetch(
                "SELECT * FROM audit_events ORDER BY id DESC LIMIT $1", int(limit)
            )
        return [dict(row) for row in rows]

    async def record_tick(
        self,
        *,
        asset_id: str,
        price: float,
        size: float = 0.0,
        side: str | None = None,
        source: str | None = None,
        time: datetime | None = None,
    ) -> None:
        timestamp = time or datetime.now(UTC)
        async with self._require_pool().acquire() as connection:
            await connection.execute(
                "INSERT INTO market_ticks (time, asset_id, price, size, side, source) "
                "VALUES ($1, $2, $3, $4, $5, $6)",
                timestamp,
                asset_id,
                float(price),
                float(size),
                side,
                source,
            )

    async def fetch_ticks(self, asset_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        async with self._require_pool().acquire() as connection:
            rows = await connection.fetch(
                "SELECT * FROM market_ticks WHERE asset_id = $1 ORDER BY time DESC LIMIT $2",
                asset_id,
                int(limit),
            )
        return [dict(row) for row in rows]

    async def health_check(self) -> bool:
        try:
            async with self._require_pool().acquire() as connection:
                await connection.execute("SELECT 1")
            return True
        except Exception as exc:
            logger.warning("postgres_health_check_failed", error=str(exc))
            return False

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None


def build_storage_backend(
    *,
    backend: str | None = None,
    database_url: str | None = None,
    db_path: str | Path | None = None,
) -> StorageBackend:
    """Construct (but do not initialize) the configured backend.

    SQLite is the default. Construction never connects, so this is safe to call
    with no server present; ``initialize()`` is where I/O happens.
    """
    name = resolve_backend_name(backend)
    if name == "sqlite":
        return SQLiteStorageBackend(db_path)
    settings = get_settings()
    dsn = database_url or settings.database_url
    return PostgresStorageBackend(dsn, timescale=(name == "timescale"))


async def open_storage_backend(
    *,
    backend: str | None = None,
    database_url: str | None = None,
    db_path: str | Path | None = None,
    allow_fallback: bool = True,
) -> StorageBackend:
    """Build and initialize the configured backend, falling back to SQLite.

    This is the recommended entry point for startup wiring. If a Postgres/
    Timescale backend is requested but ``initialize()`` fails (server down,
    bad DSN, Timescale missing) and ``allow_fallback`` is set, an initialized
    :class:`SQLiteStorageBackend` is returned instead so the process still runs.
    """
    chosen = build_storage_backend(
        backend=backend, database_url=database_url, db_path=db_path
    )
    try:
        await chosen.initialize()
        return chosen
    except Exception as exc:
        if not allow_fallback or chosen.backend_name == "sqlite":
            raise
        logger.warning(
            "storage_backend_fallback_to_sqlite",
            requested=chosen.backend_name,
            error=str(exc),
        )
        await chosen.close()
        fallback = SQLiteStorageBackend(db_path)
        await fallback.initialize()
        return fallback
