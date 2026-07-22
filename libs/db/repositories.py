"""Typed synchronous SQLite repositories on top of the fact store.

Each repository opens one connection per operation (the fact_store pattern),
uses parameterized SQL only, and writes an audit event for every state
transition inside the same transaction. Callers on the event loop should run
these methods via ``asyncio.to_thread``.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from libs.db import fact_store


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _dump_json(payload: Mapping[str, Any] | None) -> str:
    return json.dumps(dict(payload or {}), sort_keys=True, separators=(",", ":"), default=str)


def _load_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


@dataclass(frozen=True)
class IntentRecord:
    intent_id: str
    payload: dict[str, Any]
    status: str
    error: str | None
    basket_id: str | None
    idempotency_key: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class BasketLegRecord:
    leg_index: int
    payload: dict[str, Any]
    status: str
    fill: dict[str, Any] | None


@dataclass(frozen=True)
class BasketRecord:
    basket_id: str
    intent_id: str | None
    status: str
    payload: dict[str, Any]
    created_at: str
    updated_at: str
    legs: list[BasketLegRecord] = field(default_factory=list)


@dataclass(frozen=True)
class DecisionRecord:
    decision_id: str
    strategy_id: str
    market_id: str | None
    payload: dict[str, Any]
    created_at: str


class _SQLiteRepository:
    """Shared connection/audit plumbing for the concrete repositories."""

    def __init__(self, db_path: str | Path | None = None):
        # Resolve now so every operation targets the same file even if
        # settings change later; schema init stays lazy so a corrupted DB
        # surfaces as a per-operation error the services can degrade on.
        self._db_path = fact_store._resolve_db_path(db_path)

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        path = fact_store._ensure_schema(self._db_path)
        return fact_store.connect(path)

    @staticmethod
    def _audit(
        connection: sqlite3.Connection,
        event_type: str,
        subject_type: str,
        subject_id: str,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO audit_events (event_type, actor, subject_type, subject_id, payload_json, created_at)
            VALUES (?, 'system', ?, ?, ?, ?)
            """,
            (event_type, subject_type, subject_id, _dump_json(payload), _utcnow_iso()),
        )


class IntentRepository(_SQLiteRepository):
    def save(
        self,
        intent_id: str,
        payload: Mapping[str, Any],
        status: str,
        *,
        error: str | None = None,
        basket_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> None:
        now = _utcnow_iso()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO intents (
                    intent_id, payload_json, status, error, basket_id, idempotency_key, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(intent_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    status = excluded.status,
                    error = excluded.error,
                    basket_id = COALESCE(excluded.basket_id, intents.basket_id),
                    idempotency_key = COALESCE(intents.idempotency_key, excluded.idempotency_key),
                    updated_at = excluded.updated_at
                """,
                (intent_id, _dump_json(payload), status, error, basket_id, idempotency_key, now, now),
            )
            self._audit(
                connection,
                "intent.created",
                "intent",
                intent_id,
                {"status": status, "idempotency_key": idempotency_key},
            )

    def update_status(
        self,
        intent_id: str,
        status: str,
        *,
        error: str | None = None,
        basket_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE intents
                SET status = ?,
                    error = ?,
                    basket_id = COALESCE(?, basket_id),
                    updated_at = ?
                WHERE intent_id = ?
                """,
                (status, error, basket_id, _utcnow_iso(), intent_id),
            )
            if idempotency_key is not None:
                # Attach the key only when it is still free; a signature reused
                # outside the dedupe window must not violate the UNIQUE index.
                connection.execute(
                    """
                    UPDATE intents
                    SET idempotency_key = ?
                    WHERE intent_id = ?
                      AND idempotency_key IS NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM intents
                          WHERE idempotency_key = ? AND intent_id != ?
                      )
                    """,
                    (idempotency_key, intent_id, idempotency_key, intent_id),
                )
            self._audit(
                connection,
                "intent.status_changed",
                "intent",
                intent_id,
                {"status": status, "error": error, "basket_id": basket_id},
            )

    def get(self, intent_id: str) -> IntentRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM intents WHERE intent_id = ?", (intent_id,)
            ).fetchone()
        return self._to_record(row) if row else None

    def find_by_idempotency_key(self, idempotency_key: str) -> IntentRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM intents WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
        return self._to_record(row) if row else None

    def list_all(self) -> list[IntentRecord]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM intents ORDER BY created_at").fetchall()
        return [self._to_record(row) for row in rows]

    @staticmethod
    def _to_record(row: sqlite3.Row) -> IntentRecord:
        return IntentRecord(
            intent_id=row["intent_id"],
            payload=_load_json(row["payload_json"]),
            status=row["status"],
            error=row["error"],
            basket_id=row["basket_id"],
            idempotency_key=row["idempotency_key"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class BasketRepository(_SQLiteRepository):
    def save(
        self,
        basket_id: str,
        *,
        intent_id: str | None,
        status: str,
        payload: Mapping[str, Any],
        legs: list[Mapping[str, Any]] | None = None,
    ) -> None:
        now = _utcnow_iso()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO baskets (basket_id, intent_id, status, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(basket_id) DO UPDATE SET
                    intent_id = excluded.intent_id,
                    status = excluded.status,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (basket_id, intent_id, status, _dump_json(payload), now, now),
            )
            for index, leg in enumerate(legs or []):
                leg_status = str(leg.get("status", "pending_submit"))
                connection.execute(
                    """
                    INSERT INTO basket_legs (basket_id, leg_index, payload_json, status, fill_json)
                    VALUES (?, ?, ?, ?, NULL)
                    ON CONFLICT(basket_id, leg_index) DO UPDATE SET
                        payload_json = excluded.payload_json,
                        status = excluded.status
                    """,
                    (basket_id, index, _dump_json(leg), leg_status),
                )
            self._audit(
                connection,
                "basket.created",
                "basket",
                basket_id,
                {"status": status, "intent_id": intent_id, "leg_count": len(legs or [])},
            )

    def update_status(self, basket_id: str, status: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE baskets SET status = ?, updated_at = ? WHERE basket_id = ?",
                (status, _utcnow_iso(), basket_id),
            )
            self._audit(connection, "basket.status_changed", "basket", basket_id, {"status": status})

    def update_leg(
        self,
        basket_id: str,
        leg_index: int,
        *,
        status: str,
        payload: Mapping[str, Any] | None = None,
        fill: Mapping[str, Any] | None = None,
    ) -> None:
        with self._connect() as connection:
            if payload is not None:
                connection.execute(
                    """
                    UPDATE basket_legs SET status = ?, payload_json = ?, fill_json = ?
                    WHERE basket_id = ? AND leg_index = ?
                    """,
                    (
                        status,
                        _dump_json(payload),
                        _dump_json(fill) if fill is not None else None,
                        basket_id,
                        leg_index,
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE basket_legs
                    SET status = ?, fill_json = COALESCE(?, fill_json)
                    WHERE basket_id = ? AND leg_index = ?
                    """,
                    (
                        status,
                        _dump_json(fill) if fill is not None else None,
                        basket_id,
                        leg_index,
                    ),
                )
            self._audit(
                connection,
                "basket_leg.updated",
                "basket",
                basket_id,
                {"leg_index": leg_index, "status": status, "filled": fill is not None},
            )

    def get(self, basket_id: str) -> BasketRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM baskets WHERE basket_id = ?", (basket_id,)
            ).fetchone()
            if row is None:
                return None
            leg_rows = connection.execute(
                "SELECT * FROM basket_legs WHERE basket_id = ? ORDER BY leg_index",
                (basket_id,),
            ).fetchall()
        return self._to_record(row, leg_rows)

    def list_all(self) -> list[BasketRecord]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM baskets ORDER BY created_at").fetchall()
            legs_by_basket: dict[str, list[sqlite3.Row]] = {}
            for leg_row in connection.execute(
                "SELECT * FROM basket_legs ORDER BY basket_id, leg_index"
            ).fetchall():
                legs_by_basket.setdefault(leg_row["basket_id"], []).append(leg_row)
        return [self._to_record(row, legs_by_basket.get(row["basket_id"], [])) for row in rows]

    @staticmethod
    def _to_record(row: sqlite3.Row, leg_rows: list[sqlite3.Row]) -> BasketRecord:
        legs = [
            BasketLegRecord(
                leg_index=leg_row["leg_index"],
                payload=_load_json(leg_row["payload_json"]),
                status=leg_row["status"],
                fill=_load_json(leg_row["fill_json"]) if leg_row["fill_json"] else None,
            )
            for leg_row in leg_rows
        ]
        return BasketRecord(
            basket_id=row["basket_id"],
            intent_id=row["intent_id"],
            status=row["status"],
            payload=_load_json(row["payload_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            legs=legs,
        )


class DecisionRepository(_SQLiteRepository):
    def save(
        self,
        decision_id: str,
        *,
        strategy_id: str,
        market_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO strategy_decisions (
                    decision_id, strategy_id, market_id, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (decision_id, strategy_id, market_id, _dump_json(payload), _utcnow_iso()),
            )
            if cursor.rowcount:
                self._audit(
                    connection,
                    "strategy.decision_recorded",
                    "strategy_decision",
                    decision_id,
                    {"strategy_id": strategy_id, "market_id": market_id},
                )

    def get(self, decision_id: str) -> DecisionRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM strategy_decisions WHERE decision_id = ?", (decision_id,)
            ).fetchone()
        return self._to_record(row) if row else None

    def list_recent(self, *, strategy_id: str | None = None, limit: int = 100) -> list[DecisionRecord]:
        query = "SELECT * FROM strategy_decisions"
        params: list[Any] = []
        if strategy_id is not None:
            query += " WHERE strategy_id = ?"
            params.append(strategy_id)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(int(limit))
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._to_record(row) for row in rows]

    @staticmethod
    def _to_record(row: sqlite3.Row) -> DecisionRecord:
        return DecisionRecord(
            decision_id=row["decision_id"],
            strategy_id=row["strategy_id"],
            market_id=row["market_id"],
            payload=_load_json(row["payload_json"]),
            created_at=row["created_at"],
        )
