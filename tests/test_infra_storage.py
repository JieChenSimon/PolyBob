"""P4: one storage interface, Timescale-capable, SQLite default + fallback."""

from __future__ import annotations

import asyncio

import pytest

from libs.db import (
    PostgresStorageBackend,
    SQLiteStorageBackend,
    build_storage_backend,
    connect,
    open_storage_backend,
    resolve_backend_name,
)
from libs.db import migrations, storage


# --- backend selection / config -------------------------------------------


def test_default_backend_is_sqlite(monkeypatch):
    monkeypatch.delenv("POLYBOB_STORAGE_BACKEND", raising=False)
    assert resolve_backend_name() == "sqlite"
    assert isinstance(build_storage_backend(), SQLiteStorageBackend)


def test_backend_selection_postgres_and_timescale(monkeypatch):
    monkeypatch.setenv("POLYBOB_STORAGE_BACKEND", "timescale")
    backend = build_storage_backend(database_url="postgresql+asyncpg://u:p@localhost/db")
    assert isinstance(backend, PostgresStorageBackend)
    assert backend.backend_name == "timescale"

    monkeypatch.setenv("POLYBOB_STORAGE_BACKEND", "postgres")
    backend = build_storage_backend(database_url="postgresql+asyncpg://u:p@localhost/db")
    assert isinstance(backend, PostgresStorageBackend)
    assert backend.backend_name == "postgres"


def test_invalid_backend_name_raises(monkeypatch):
    monkeypatch.setenv("POLYBOB_STORAGE_BACKEND", "mysql")
    with pytest.raises(ValueError):
        resolve_backend_name()


def test_asyncpg_dsn_strips_driver_suffix():
    assert (
        storage.asyncpg_dsn("postgresql+asyncpg://u:p@host:5432/db")
        == "postgresql://u:p@host:5432/db"
    )


# --- migrations (importable, unit-tested against sqlite) ------------------


def test_sqlite_migrations_create_tables(tmp_path):
    db_path = tmp_path / "infra.sqlite3"
    with connect(db_path) as connection:
        migrations.apply_sqlite(connection)
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    names = {row["name"] for row in rows}
    assert {"audit_events", "market_ticks"} <= names


def test_postgres_ddl_includes_hypertable_only_with_timescale():
    with_ts = "\n".join(migrations.postgres_ddl(timescale=True))
    assert "create_hypertable(" in with_ts
    assert "CREATE EXTENSION IF NOT EXISTS timescaledb" in with_ts
    assert "TIMESTAMPTZ" in with_ts
    assert "(asset_id, time DESC)" in with_ts

    without_ts = "\n".join(migrations.postgres_ddl(timescale=False))
    assert "create_hypertable(" not in without_ts
    assert "CREATE EXTENSION" not in without_ts


def test_ddl_for_unknown_dialect_raises():
    with pytest.raises(ValueError):
        migrations.ddl_for("oracle")  # type: ignore[arg-type]


# --- sqlite backend round-trip (async facade, no server) ------------------


@pytest.mark.asyncio
async def test_sqlite_backend_roundtrip(tmp_path):
    db_path = tmp_path / "roundtrip.sqlite3"
    backend = await open_storage_backend(backend="sqlite", db_path=db_path)
    try:
        assert backend.backend_name == "sqlite"
        assert await backend.health_check() is True

        event_id = await backend.append_audit_event(
            "case.created",
            actor="test",
            subject_type="case",
            subject_id="c-1",
            payload={"score": 0.9},
        )
        assert event_id == 1
        events = await backend.fetch_audit_events(limit=10)
        assert events[0]["event_type"] == "case.created"

        await backend.record_tick(asset_id="BTC", price=0.61, size=12.0, side="buy")
        await backend.record_tick(asset_id="BTC", price=0.62, size=5.0, side="sell")
        ticks = await backend.fetch_ticks("BTC", limit=10)
        assert len(ticks) == 2
        assert {t["asset_id"] for t in ticks} == {"BTC"}
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_postgres_backend_falls_back_to_sqlite_when_unreachable(tmp_path):
    db_path = tmp_path / "fallback.sqlite3"
    # Port 1 refuses immediately, so the fallback path is exercised fast.
    backend = await open_storage_backend(
        backend="postgres",
        database_url="postgresql://user:pass@127.0.0.1:1/nope",
        db_path=db_path,
        allow_fallback=True,
    )
    try:
        assert isinstance(backend, SQLiteStorageBackend)
        assert backend.backend_name == "sqlite"
        assert await backend.append_audit_event("fell_back") == 1
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_postgres_backend_raises_without_fallback():
    with pytest.raises(Exception):
        await open_storage_backend(
            backend="postgres",
            database_url="postgresql://user:pass@127.0.0.1:1/nope",
            allow_fallback=False,
        )


# --- live Postgres/Timescale (skipped unless a server is reachable) -------


def _database_url() -> str:
    from libs.config import get_settings

    return get_settings().database_url


async def _postgres_reachable(dsn: str) -> bool:
    try:
        import asyncpg
    except ImportError:  # pragma: no cover
        return False
    try:
        conn = await asyncio.wait_for(
            asyncpg.connect(storage.asyncpg_dsn(dsn)), timeout=2.0
        )
    except Exception:
        return False
    await conn.close()
    return True


@pytest.mark.asyncio
async def test_live_timescale_roundtrip():
    dsn = _database_url()
    if not await _postgres_reachable(dsn):
        pytest.skip("no live Postgres/TimescaleDB reachable via DATABASE_URL")

    backend = PostgresStorageBackend(dsn, timescale=True)
    await backend.initialize()
    try:
        assert await backend.health_check() is True
        event_id = await backend.append_audit_event("live.audit", payload={"ok": True})
        assert event_id is not None
        await backend.record_tick(asset_id="LIVE", price=0.5, size=1.0, side="buy")
        ticks = await backend.fetch_ticks("LIVE", limit=5)
        assert any(t["asset_id"] == "LIVE" for t in ticks)
    finally:
        await backend.close()
