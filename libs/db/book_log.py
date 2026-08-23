"""Append-only raw order-book event log backed by SQLite (WAL).

Stores raw provider payloads (``book`` / ``price_change`` / trade messages)
before any processing, so book reconstruction can be replayed deterministically
(libs/polymarket/replay). Writes are batched: events buffer in memory and a
background task flushes every ``flush_max_events`` events or
``flush_interval_seconds`` seconds. The buffer is bounded — on overflow the
oldest *raw-log* entries are dropped and counted; the ingest path is never
blocked. Dropping here only loses audit-log rows, not canonical book events.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Mapping

import structlog

from libs.db import fact_store

logger = structlog.get_logger()

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS raw_book_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        asset_id TEXT,
        event_type TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        receive_ts TEXT NOT NULL,
        source_ts TEXT,
        quality TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_raw_book_events_asset_receive
    ON raw_book_events (asset_id, receive_ts)
    """,
)


def _to_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _from_iso(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@dataclass(frozen=True)
class BookLogRecord:
    """One logged raw event, payload decoded."""

    id: int
    asset_id: str | None
    event_type: str
    payload: dict[str, Any]
    receive_ts: datetime
    source_ts: datetime | None
    quality: str | None


class BookEventLog:
    """Batched append-only writer / reader for ``raw_book_events``."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        flush_max_events: int = 200,
        flush_interval_seconds: float = 2.0,
        max_buffer_events: int = 10_000,
        retention_days: int = 0,
        max_rows: int = 500_000,
    ) -> None:
        self._db_path = db_path
        self.flush_max_events = max(1, flush_max_events)
        self.flush_interval_seconds = flush_interval_seconds
        self.max_buffer_events = max(1, max_buffer_events)
        self.retention_days = max(0, int(retention_days))
        self.max_rows = max(1, int(max_rows))
        self._last_prune_monotonic = 0.0

        self._buffer: list[tuple] = []
        self._lock = threading.Lock()
        self.dropped_events = 0
        self._flush_task: asyncio.Task | None = None
        self._flush_signal: asyncio.Event | None = None
        self._ensure_schema()

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        """Start the background flush task (idempotent)."""
        if self._flush_task is not None and not self._flush_task.done():
            return
        self._flush_signal = asyncio.Event()
        self._flush_task = asyncio.create_task(self._flush_loop())

    async def stop(self) -> None:
        """Stop the background task and flush remaining events."""
        if self._flush_task is not None:
            self._flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._flush_task
            self._flush_task = None
        self._flush_signal = None
        self.flush()

    async def _flush_loop(self) -> None:
        assert self._flush_signal is not None
        while True:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(
                    self._flush_signal.wait(), timeout=self.flush_interval_seconds
                )
            self._flush_signal.clear()
            try:
                await asyncio.to_thread(self.flush)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # log write failures must not kill ingest
                logger.error("book_log_flush_failed", error=str(exc))

    # -- write path --------------------------------------------------------

    def log_event(
        self,
        *,
        asset_id: str | None,
        event_type: str,
        payload: Mapping[str, Any],
        receive_ts: datetime,
        source_ts: datetime | None = None,
        quality: str | None = None,
    ) -> None:
        """Buffer one raw event. Never blocks; drops oldest on overflow."""
        row = (
            asset_id,
            event_type,
            json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), default=str),
            receive_ts.isoformat(),
            _to_iso(source_ts),
            quality,
        )
        with self._lock:
            if len(self._buffer) >= self.max_buffer_events:
                self._buffer.pop(0)
                self.dropped_events += 1
            self._buffer.append(row)
            should_flush = len(self._buffer) >= self.flush_max_events
        if should_flush and self._flush_signal is not None:
            self._flush_signal.set()

    def flush(self) -> int:
        """Synchronously write all buffered events; returns rows written."""
        with self._lock:
            if not self._buffer:
                return 0
            rows, self._buffer = self._buffer, []
        with contextlib.closing(self._connect()) as connection, connection:
            connection.executemany(
                """
                INSERT INTO raw_book_events
                    (asset_id, event_type, payload_json, receive_ts, source_ts, quality)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            self._prune_if_due(connection)
        return len(rows)

    def _prune_if_due(self, connection) -> None:
        """Bound the append-only log by age and row count.

        Raw capture is useful for replay, but an unbounded SQLite file is not a
        safe default for a long-running workstation. Pruning is done in the
        same transaction as a batch flush and at most hourly.
        """
        import time
        now = time.monotonic()
        if now - self._last_prune_monotonic < 3600.0:
            return
        self._last_prune_monotonic = now
        if self.retention_days > 0:
            connection.execute(
                "DELETE FROM raw_book_events WHERE julianday(receive_ts) < julianday('now', ?)",
                (f"-{self.retention_days} days",),
            )
        connection.execute(
            """DELETE FROM raw_book_events
               WHERE id NOT IN (SELECT id FROM raw_book_events ORDER BY id DESC LIMIT ?)""",
            (self.max_rows,),
        )

    # -- read path ---------------------------------------------------------

    def read_events(
        self,
        asset_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Iterator[BookLogRecord]:
        """Iterate logged events for one asset in append (id) order.

        ``start``/``end`` bound the local ``receive_ts`` (inclusive).
        Buffered events are flushed first so reads see everything logged.
        """
        self.flush()
        query = (
            "SELECT id, asset_id, event_type, payload_json, receive_ts, source_ts, quality "
            "FROM raw_book_events WHERE asset_id = ?"
        )
        params: list[Any] = [asset_id]
        if start is not None:
            query += " AND receive_ts >= ?"
            params.append(start.isoformat())
        if end is not None:
            query += " AND receive_ts <= ?"
            params.append(end.isoformat())
        query += " ORDER BY id ASC"

        connection = self._connect()
        try:
            for row in connection.execute(query, params):
                receive_ts = _from_iso(row["receive_ts"])
                if receive_ts is None:
                    continue
                try:
                    payload = json.loads(row["payload_json"])
                except (TypeError, ValueError):
                    payload = {}
                yield BookLogRecord(
                    id=int(row["id"]),
                    asset_id=row["asset_id"],
                    event_type=row["event_type"],
                    payload=payload if isinstance(payload, dict) else {},
                    receive_ts=receive_ts,
                    source_ts=_from_iso(row["source_ts"]),
                    quality=row["quality"],
                )
        finally:
            connection.close()

    # -- internals ---------------------------------------------------------

    def _connect(self):
        return fact_store.connect(self._db_path)

    def _ensure_schema(self) -> None:
        with contextlib.closing(self._connect()) as connection, connection:
            for statement in _SCHEMA_STATEMENTS:
                connection.execute(statement)
