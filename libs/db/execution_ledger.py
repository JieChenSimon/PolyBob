"""Authoritative, append-only execution fill ledger.

One fill is the transaction boundary: the immutable fill event, account cash,
instrument position, fees, and realised PnL either all commit or none do.  The
mutable account/position rows are projections only; ``replay`` rebuilds them
from the fill ledger so recovery can detect drift instead of trusting a stale
cache.

This first slice deliberately models spot-style cash accounting.  Margin,
funding, contract multipliers, marks, and unrealised PnL need explicit product
contracts before they can be added safely.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from libs.db import fact_store


ZERO = Decimal("0")


class ExecutionLedgerError(RuntimeError):
    """Base error for durable execution accounting."""


class UnknownExecutionAccount(ExecutionLedgerError):
    """Raised when a fill targets an account that was never registered."""


class FillConflict(ExecutionLedgerError):
    """Raised when a fill id is reused with different economic content."""


@dataclass(frozen=True)
class FillCommand:
    fill_id: str
    account_id: str
    order_id: str
    instrument_id: str
    side: str
    quantity: Decimal | str | int | float
    price: Decimal | str | int | float
    fee: Decimal | str | int | float = ZERO
    currency: str = "USD"
    executed_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PositionSnapshot:
    instrument_id: str
    quantity: Decimal
    avg_cost: Decimal
    total_fees: Decimal
    gross_realized_pnl: Decimal
    net_realized_pnl: Decimal


@dataclass(frozen=True)
class AccountSnapshot:
    account_id: str
    currency: str
    initial_cash: Decimal
    cash: Decimal
    total_fees: Decimal
    gross_realized_pnl: Decimal
    net_realized_pnl: Decimal
    positions: dict[str, PositionSnapshot]


@dataclass(frozen=True)
class FillReceipt:
    sequence: int
    fill_id: str
    replayed: bool
    cash_after: Decimal
    position_after: Decimal
    avg_cost_after: Decimal
    fee: Decimal
    gross_realized_delta: Decimal
    net_realized_delta: Decimal


@dataclass(frozen=True)
class ProjectionVerification:
    consistent: bool
    replayed: AccountSnapshot
    projected: AccountSnapshot
    mismatches: tuple[str, ...]


_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS execution_accounts (
        account_id TEXT PRIMARY KEY,
        currency TEXT NOT NULL,
        initial_cash TEXT NOT NULL,
        cash TEXT NOT NULL,
        total_fees TEXT NOT NULL DEFAULT '0',
        gross_realized_pnl TEXT NOT NULL DEFAULT '0',
        net_realized_pnl TEXT NOT NULL DEFAULT '0',
        version INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS execution_positions (
        account_id TEXT NOT NULL,
        instrument_id TEXT NOT NULL,
        quantity TEXT NOT NULL,
        avg_cost TEXT NOT NULL,
        total_fees TEXT NOT NULL DEFAULT '0',
        gross_realized_pnl TEXT NOT NULL DEFAULT '0',
        net_realized_pnl TEXT NOT NULL DEFAULT '0',
        updated_at TEXT NOT NULL,
        PRIMARY KEY (account_id, instrument_id),
        FOREIGN KEY (account_id) REFERENCES execution_accounts(account_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS execution_fill_ledger (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        fill_id TEXT NOT NULL UNIQUE,
        request_hash TEXT NOT NULL,
        account_id TEXT NOT NULL,
        order_id TEXT NOT NULL,
        instrument_id TEXT NOT NULL,
        side TEXT NOT NULL,
        quantity TEXT NOT NULL,
        price TEXT NOT NULL,
        fee TEXT NOT NULL,
        currency TEXT NOT NULL,
        cash_delta TEXT NOT NULL,
        cash_after TEXT NOT NULL,
        position_after TEXT NOT NULL,
        avg_cost_after TEXT NOT NULL,
        gross_realized_delta TEXT NOT NULL,
        net_realized_delta TEXT NOT NULL,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        executed_at TEXT NOT NULL,
        executed_at_explicit INTEGER NOT NULL DEFAULT 0,
        recorded_at TEXT NOT NULL,
        FOREIGN KEY (account_id) REFERENCES execution_accounts(account_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_execution_fill_account_sequence
    ON execution_fill_ledger (account_id, sequence)
    """,
    """
    CREATE TRIGGER IF NOT EXISTS execution_fill_ledger_no_update
    BEFORE UPDATE ON execution_fill_ledger
    BEGIN
        SELECT RAISE(ABORT, 'execution_fill_ledger is append-only');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS execution_fill_ledger_no_delete
    BEFORE DELETE ON execution_fill_ledger
    BEGIN
        SELECT RAISE(ABORT, 'execution_fill_ledger is append-only');
    END
    """,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _decimal(value: Decimal | str | int | float, field_name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite decimal") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field_name} must be a finite decimal")
    return parsed


def _text(value: Decimal) -> str:
    if value == ZERO:
        return "0"
    return format(value.normalize(), "f")


def _position_after_fill(
    current_quantity: Decimal,
    current_avg_cost: Decimal,
    signed_quantity: Decimal,
    price: Decimal,
) -> tuple[Decimal, Decimal, Decimal]:
    """Return quantity, average cost and gross realised PnL for one fill."""
    if current_quantity == ZERO or current_quantity * signed_quantity > ZERO:
        new_quantity = current_quantity + signed_quantity
        weighted = (
            abs(current_quantity) * current_avg_cost + abs(signed_quantity) * price
        )
        return new_quantity, weighted / abs(new_quantity), ZERO

    closed_quantity = min(abs(current_quantity), abs(signed_quantity))
    direction = Decimal("1") if current_quantity > ZERO else Decimal("-1")
    gross_realized = (price - current_avg_cost) * closed_quantity * direction
    new_quantity = current_quantity + signed_quantity
    if new_quantity == ZERO:
        return ZERO, ZERO, gross_realized
    if abs(signed_quantity) > abs(current_quantity):
        return new_quantity, price, gross_realized
    return new_quantity, current_avg_cost, gross_realized


class ExecutionLedger:
    """SQLite repository and accounting service for authoritative fills."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = fact_store._resolve_db_path(db_path)
        self._ready = False
        self._schema_lock = threading.Lock()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        connection = fact_store.connect(self._db_path)
        if not self._ready:
            with self._schema_lock:
                if not self._ready:
                    for statement in _SCHEMA:
                        connection.execute(statement)
                    connection.commit()
                    self._ready = True
        return connection

    def register_account(
        self,
        account_id: str,
        *,
        initial_cash: Decimal | str | int | float,
        currency: str = "USD",
    ) -> AccountSnapshot:
        account_id = account_id.strip()
        currency = currency.strip().upper()
        cash = _decimal(initial_cash, "initial_cash")
        if not account_id or not currency:
            raise ValueError("account_id and currency are required")
        if cash < ZERO:
            raise ValueError("initial_cash must be non-negative")

        now = _now()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM execution_accounts WHERE account_id = ?", (account_id,)
            ).fetchone()
            if existing is not None:
                if existing["currency"] != currency or Decimal(existing["initial_cash"]) != cash:
                    raise ExecutionLedgerError(
                        "account already exists with different currency or initial cash"
                    )
            else:
                connection.execute(
                    """
                    INSERT INTO execution_accounts (
                        account_id, currency, initial_cash, cash, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (account_id, currency, _text(cash), _text(cash), now, now),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return self.get_account(account_id)

    def apply_fill(self, command: FillCommand) -> FillReceipt:
        executed_at_explicit = command.executed_at is not None
        normalized = self._normalize(command)
        request_hash = self._request_hash(normalized)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM execution_fill_ledger WHERE fill_id = ?",
                (normalized.fill_id,),
            ).fetchone()
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise FillConflict(
                        f"fill_id {normalized.fill_id!r} was already used with different content"
                    )
                if (
                    executed_at_explicit
                    and bool(existing["executed_at_explicit"])
                    and existing["executed_at"] != normalized.executed_at
                ):
                    raise FillConflict(
                        f"fill_id {normalized.fill_id!r} was already used with a different "
                        "explicit executed_at"
                    )
                connection.rollback()
                return self._receipt(existing, replayed=True)

            account = connection.execute(
                "SELECT * FROM execution_accounts WHERE account_id = ?",
                (normalized.account_id,),
            ).fetchone()
            if account is None:
                raise UnknownExecutionAccount(normalized.account_id)
            if account["currency"] != normalized.currency:
                raise ExecutionLedgerError(
                    f"fill currency {normalized.currency} does not match account currency "
                    f"{account['currency']}"
                )

            position = connection.execute(
                """
                SELECT * FROM execution_positions
                WHERE account_id = ? AND instrument_id = ?
                """,
                (normalized.account_id, normalized.instrument_id),
            ).fetchone()
            current_quantity = Decimal(position["quantity"]) if position else ZERO
            current_avg = Decimal(position["avg_cost"]) if position else ZERO
            current_position_fees = Decimal(position["total_fees"]) if position else ZERO
            current_position_gross = (
                Decimal(position["gross_realized_pnl"]) if position else ZERO
            )
            current_position_net = Decimal(position["net_realized_pnl"]) if position else ZERO

            signed_quantity = (
                normalized.quantity if normalized.side == "buy" else -normalized.quantity
            )
            new_quantity, new_avg, gross_delta = _position_after_fill(
                current_quantity, current_avg, signed_quantity, normalized.price
            )
            net_delta = gross_delta - normalized.fee
            cash_delta = -signed_quantity * normalized.price - normalized.fee
            cash_after = Decimal(account["cash"]) + cash_delta
            total_fees = Decimal(account["total_fees"]) + normalized.fee
            gross_after = Decimal(account["gross_realized_pnl"]) + gross_delta
            net_after = Decimal(account["net_realized_pnl"]) + net_delta
            recorded_at = _now()

            cursor = connection.execute(
                """
                INSERT INTO execution_fill_ledger (
                    fill_id, request_hash, account_id, order_id, instrument_id,
                    side, quantity, price, fee, currency, cash_delta, cash_after,
                    position_after, avg_cost_after, gross_realized_delta,
                    net_realized_delta, metadata_json, executed_at,
                    executed_at_explicit, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized.fill_id,
                    request_hash,
                    normalized.account_id,
                    normalized.order_id,
                    normalized.instrument_id,
                    normalized.side,
                    _text(normalized.quantity),
                    _text(normalized.price),
                    _text(normalized.fee),
                    normalized.currency,
                    _text(cash_delta),
                    _text(cash_after),
                    _text(new_quantity),
                    _text(new_avg),
                    _text(gross_delta),
                    _text(net_delta),
                    json.dumps(
                        normalized.metadata,
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                    ),
                    normalized.executed_at,
                    1 if executed_at_explicit else 0,
                    recorded_at,
                ),
            )
            self._write_projections(
                connection,
                normalized,
                cash_after=cash_after,
                account_total_fees=total_fees,
                account_gross_realized=gross_after,
                account_net_realized=net_after,
                quantity=new_quantity,
                avg_cost=new_avg,
                position_total_fees=current_position_fees + normalized.fee,
                position_gross_realized=current_position_gross + gross_delta,
                position_net_realized=current_position_net + net_delta,
                updated_at=recorded_at,
            )
            row = connection.execute(
                "SELECT * FROM execution_fill_ledger WHERE sequence = ?",
                (cursor.lastrowid,),
            ).fetchone()
            connection.commit()
            return self._receipt(row, replayed=False)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _write_projections(
        self,
        connection: sqlite3.Connection,
        command: FillCommand,
        *,
        cash_after: Decimal,
        account_total_fees: Decimal,
        account_gross_realized: Decimal,
        account_net_realized: Decimal,
        quantity: Decimal,
        avg_cost: Decimal,
        position_total_fees: Decimal,
        position_gross_realized: Decimal,
        position_net_realized: Decimal,
        updated_at: str,
    ) -> None:
        """Write mutable projections inside the caller's fill transaction."""
        connection.execute(
            """
            UPDATE execution_accounts
            SET cash = ?, total_fees = ?, gross_realized_pnl = ?,
                net_realized_pnl = ?, version = version + 1, updated_at = ?
            WHERE account_id = ?
            """,
            (
                _text(cash_after),
                _text(account_total_fees),
                _text(account_gross_realized),
                _text(account_net_realized),
                updated_at,
                command.account_id,
            ),
        )
        connection.execute(
            """
            INSERT INTO execution_positions (
                account_id, instrument_id, quantity, avg_cost, total_fees,
                gross_realized_pnl, net_realized_pnl, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id, instrument_id) DO UPDATE SET
                quantity = excluded.quantity,
                avg_cost = excluded.avg_cost,
                total_fees = excluded.total_fees,
                gross_realized_pnl = excluded.gross_realized_pnl,
                net_realized_pnl = excluded.net_realized_pnl,
                updated_at = excluded.updated_at
            """,
            (
                command.account_id,
                command.instrument_id,
                _text(quantity),
                _text(avg_cost),
                _text(position_total_fees),
                _text(position_gross_realized),
                _text(position_net_realized),
                updated_at,
            ),
        )

    def get_account(self, account_id: str) -> AccountSnapshot:
        with self._connect() as connection:
            account = connection.execute(
                "SELECT * FROM execution_accounts WHERE account_id = ?", (account_id,)
            ).fetchone()
            if account is None:
                raise UnknownExecutionAccount(account_id)
            position_rows = connection.execute(
                """
                SELECT * FROM execution_positions
                WHERE account_id = ? ORDER BY instrument_id
                """,
                (account_id,),
            ).fetchall()
        return self._snapshot(account, position_rows)

    def replay(self, account_id: str) -> AccountSnapshot:
        with self._connect() as connection:
            account = connection.execute(
                "SELECT * FROM execution_accounts WHERE account_id = ?", (account_id,)
            ).fetchone()
            if account is None:
                raise UnknownExecutionAccount(account_id)
            rows = connection.execute(
                """
                SELECT * FROM execution_fill_ledger
                WHERE account_id = ? ORDER BY sequence
                """,
                (account_id,),
            ).fetchall()

        cash = Decimal(account["initial_cash"])
        total_fees = ZERO
        gross_total = ZERO
        net_total = ZERO
        positions: dict[str, PositionSnapshot] = {}
        for row in rows:
            instrument = row["instrument_id"]
            current = positions.get(
                instrument,
                PositionSnapshot(instrument, ZERO, ZERO, ZERO, ZERO, ZERO),
            )
            quantity = Decimal(row["quantity"])
            signed_quantity = quantity if row["side"] == "buy" else -quantity
            fee = Decimal(row["fee"])
            price = Decimal(row["price"])
            new_quantity, new_avg, gross_delta = _position_after_fill(
                current.quantity, current.avg_cost, signed_quantity, price
            )
            net_delta = gross_delta - fee
            cash += -signed_quantity * price - fee
            total_fees += fee
            gross_total += gross_delta
            net_total += net_delta
            positions[instrument] = PositionSnapshot(
                instrument_id=instrument,
                quantity=new_quantity,
                avg_cost=new_avg,
                total_fees=current.total_fees + fee,
                gross_realized_pnl=current.gross_realized_pnl + gross_delta,
                net_realized_pnl=current.net_realized_pnl + net_delta,
            )
        return AccountSnapshot(
            account_id=account_id,
            currency=account["currency"],
            initial_cash=Decimal(account["initial_cash"]),
            cash=cash,
            total_fees=total_fees,
            gross_realized_pnl=gross_total,
            net_realized_pnl=net_total,
            positions=positions,
        )

    def verify_projection(self, account_id: str) -> ProjectionVerification:
        replayed = self.replay(account_id)
        projected = self.get_account(account_id)
        mismatches: list[str] = []
        for field_name in (
            "currency",
            "initial_cash",
            "cash",
            "total_fees",
            "gross_realized_pnl",
            "net_realized_pnl",
        ):
            if getattr(replayed, field_name) != getattr(projected, field_name):
                mismatches.append(field_name)
        if replayed.positions != projected.positions:
            mismatches.append("positions")
        return ProjectionVerification(
            consistent=not mismatches,
            replayed=replayed,
            projected=projected,
            mismatches=tuple(mismatches),
        )

    @staticmethod
    def _normalize(command: FillCommand) -> FillCommand:
        fill_id = command.fill_id.strip()
        account_id = command.account_id.strip()
        order_id = command.order_id.strip()
        instrument_id = command.instrument_id.strip().upper()
        side = command.side.strip().lower()
        currency = command.currency.strip().upper()
        quantity = _decimal(command.quantity, "quantity")
        price = _decimal(command.price, "price")
        fee = _decimal(command.fee, "fee")
        if not all((fill_id, account_id, order_id, instrument_id, currency)):
            raise ValueError(
                "fill_id, account_id, order_id, instrument_id and currency are required"
            )
        if side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        if quantity <= ZERO or price <= ZERO or fee < ZERO:
            raise ValueError("quantity and price must be positive; fee must be non-negative")
        executed_at = command.executed_at or _now()
        try:
            parsed_at = datetime.fromisoformat(executed_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("executed_at must be ISO-8601") from exc
        if parsed_at.tzinfo is None or parsed_at.utcoffset() is None:
            raise ValueError("explicit executed_at must include a UTC offset or Z")
        executed_at = parsed_at.astimezone(UTC).isoformat()
        return FillCommand(
            fill_id=fill_id,
            account_id=account_id,
            order_id=order_id,
            instrument_id=instrument_id,
            side=side,
            quantity=quantity,
            price=price,
            fee=fee,
            currency=currency,
            executed_at=executed_at,
            metadata=dict(command.metadata),
        )

    @staticmethod
    def _request_hash(command: FillCommand) -> str:
        payload = asdict(command)
        # A retry may omit the venue timestamp and receive a fresh local default.
        # Fill identity is therefore its economic content, not when this process
        # happened to record it.  The first accepted timestamp remains immutable
        # in the ledger row.
        payload.pop("executed_at", None)
        payload["quantity"] = _text(command.quantity)  # type: ignore[arg-type]
        payload["price"] = _text(command.price)  # type: ignore[arg-type]
        payload["fee"] = _text(command.fee)  # type: ignore[arg-type]
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), default=str
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _receipt(row: sqlite3.Row, *, replayed: bool) -> FillReceipt:
        return FillReceipt(
            sequence=int(row["sequence"]),
            fill_id=row["fill_id"],
            replayed=replayed,
            cash_after=Decimal(row["cash_after"]),
            position_after=Decimal(row["position_after"]),
            avg_cost_after=Decimal(row["avg_cost_after"]),
            fee=Decimal(row["fee"]),
            gross_realized_delta=Decimal(row["gross_realized_delta"]),
            net_realized_delta=Decimal(row["net_realized_delta"]),
        )

    @staticmethod
    def _snapshot(
        account: sqlite3.Row, position_rows: list[sqlite3.Row]
    ) -> AccountSnapshot:
        positions = {
            row["instrument_id"]: PositionSnapshot(
                instrument_id=row["instrument_id"],
                quantity=Decimal(row["quantity"]),
                avg_cost=Decimal(row["avg_cost"]),
                total_fees=Decimal(row["total_fees"]),
                gross_realized_pnl=Decimal(row["gross_realized_pnl"]),
                net_realized_pnl=Decimal(row["net_realized_pnl"]),
            )
            for row in position_rows
        }
        return AccountSnapshot(
            account_id=account["account_id"],
            currency=account["currency"],
            initial_cash=Decimal(account["initial_cash"]),
            cash=Decimal(account["cash"]),
            total_fees=Decimal(account["total_fees"]),
            gross_realized_pnl=Decimal(account["gross_realized_pnl"]),
            net_realized_pnl=Decimal(account["net_realized_pnl"]),
            positions=positions,
        )


__all__ = [
    "AccountSnapshot",
    "ExecutionLedger",
    "ExecutionLedgerError",
    "FillCommand",
    "FillConflict",
    "FillReceipt",
    "PositionSnapshot",
    "ProjectionVerification",
    "UnknownExecutionAccount",
]
