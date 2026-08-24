"""Atomicity, idempotency, append-only history, and replay for execution fills."""

import sqlite3
from decimal import Decimal

import pytest

from libs.db.execution_ledger import (
    ExecutionLedger,
    FillCommand,
    FillConflict,
    SettlementCommand,
    SettlementError,
)


def _fill(fill_id: str, side: str, quantity: str, price: str, fee: str) -> FillCommand:
    return FillCommand(
        fill_id=fill_id,
        account_id="paper-main",
        order_id=f"order-{fill_id}",
        instrument_id="AAPL",
        side=side,
        quantity=quantity,
        price=price,
        fee=fee,
        executed_at=f"2026-08-13T0{fill_id[-1]}:00:00+00:00",
    )


def _settlement(
    settlement_id: str,
    *,
    quantity: str = "10",
    payout: str = "1",
) -> SettlementCommand:
    return SettlementCommand(
        settlement_id=settlement_id,
        account_id="paper-main",
        market_id="market-1",
        instrument_id="AAPL",
        quantity=quantity,
        payout_per_token=payout,
        settled_at="2026-08-13T10:00:00+00:00",
    )


def test_fill_atomically_updates_cash_position_fees_and_realized_pnl(tmp_path):
    ledger = ExecutionLedger(tmp_path / "ledger.sqlite3")
    ledger.register_account("paper-main", initial_cash="10000", currency="USD")

    opened = ledger.apply_fill(_fill("fill-1", "buy", "10", "100", "1"))
    closed = ledger.apply_fill(_fill("fill-2", "sell", "4", "110", "0.5"))

    assert opened.cash_after == Decimal("8999")
    assert opened.position_after == Decimal("10")
    assert closed.cash_after == Decimal("9438.5")
    assert closed.position_after == Decimal("6")
    assert closed.avg_cost_after == Decimal("100")
    assert closed.gross_realized_delta == Decimal("40")
    assert closed.net_realized_delta == Decimal("39.5")

    account = ledger.get_account("paper-main")
    assert account.total_fees == Decimal("1.5")
    assert account.gross_realized_pnl == Decimal("40")
    assert account.net_realized_pnl == Decimal("38.5")
    assert account.positions["AAPL"].quantity == Decimal("6")
    assert ledger.verify_projection("paper-main").consistent is True


def test_duplicate_fill_is_idempotent_but_conflicting_payload_is_rejected(tmp_path):
    ledger = ExecutionLedger(tmp_path / "ledger.sqlite3")
    ledger.register_account("paper-main", initial_cash="10000")
    command = _fill("fill-1", "buy", "10", "100", "1")

    first = ledger.apply_fill(command)
    replay = ledger.apply_fill(command)

    assert replay.sequence == first.sequence
    assert replay.replayed is True
    assert ledger.get_account("paper-main").cash == Decimal("8999")

    with pytest.raises(FillConflict):
        ledger.apply_fill(_fill("fill-1", "buy", "11", "100", "1"))


def test_retry_without_venue_timestamp_remains_idempotent(tmp_path):
    ledger = ExecutionLedger(tmp_path / "ledger.sqlite3")
    ledger.register_account("paper-main", initial_cash="10000")
    command = FillCommand(
        fill_id="venue-fill-1",
        account_id="paper-main",
        order_id="order-1",
        instrument_id="AAPL",
        side="buy",
        quantity="1",
        price="100",
    )

    first = ledger.apply_fill(command)
    replay = ledger.apply_fill(command)

    assert replay.sequence == first.sequence
    assert replay.replayed is True


def test_two_different_explicit_execution_times_conflict(tmp_path):
    ledger = ExecutionLedger(tmp_path / "ledger.sqlite3")
    ledger.register_account("paper-main", initial_cash="10000")
    first = _fill("fill-1", "buy", "1", "100", "0")
    ledger.apply_fill(first)

    conflicting = FillCommand(
        **{**first.__dict__, "executed_at": "2026-08-13T09:30:00+00:00"}
    )
    with pytest.raises(FillConflict, match="explicit executed_at"):
        ledger.apply_fill(conflicting)


def test_explicit_execution_time_requires_timezone(tmp_path):
    ledger = ExecutionLedger(tmp_path / "ledger.sqlite3")
    ledger.register_account("paper-main", initial_cash="10000")
    command = FillCommand(
        **{
            **_fill("fill-1", "buy", "1", "100", "0").__dict__,
            "executed_at": "2026-08-13T09:30:00",
        }
    )

    with pytest.raises(ValueError, match="UTC offset or Z"):
        ledger.apply_fill(command)


def test_projection_failure_rolls_back_fill_and_every_balance(tmp_path, monkeypatch):
    ledger = ExecutionLedger(tmp_path / "ledger.sqlite3")
    ledger.register_account("paper-main", initial_cash="10000")

    def fail_projection(*args, **kwargs):
        raise RuntimeError("injected projection failure")

    monkeypatch.setattr(ledger, "_write_projections", fail_projection)
    with pytest.raises(RuntimeError, match="injected"):
        ledger.apply_fill(_fill("fill-1", "buy", "10", "100", "1"))

    assert ledger.get_account("paper-main").cash == Decimal("10000")
    with sqlite3.connect(ledger.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM execution_fill_ledger").fetchone()[0] == 0


def test_fill_ledger_rejects_update_and_delete(tmp_path):
    ledger = ExecutionLedger(tmp_path / "ledger.sqlite3")
    ledger.register_account("paper-main", initial_cash="10000")
    ledger.apply_fill(_fill("fill-1", "buy", "10", "100", "1"))

    with sqlite3.connect(ledger.db_path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE execution_fill_ledger SET price = '1' WHERE fill_id = 'fill-1'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM execution_fill_ledger WHERE fill_id = 'fill-1'")


def test_replay_detects_projection_drift_without_mutating_history(tmp_path):
    ledger = ExecutionLedger(tmp_path / "ledger.sqlite3")
    ledger.register_account("paper-main", initial_cash="10000")
    ledger.apply_fill(_fill("fill-1", "buy", "10", "100", "1"))
    ledger.apply_fill(_fill("fill-2", "sell", "12", "110", "0.5"))

    replayed = ledger.replay("paper-main")
    assert replayed.cash == Decimal("10318.5")
    assert replayed.positions["AAPL"].quantity == Decimal("-2")
    assert replayed.positions["AAPL"].avg_cost == Decimal("110")
    assert replayed.gross_realized_pnl == Decimal("100")
    assert ledger.verify_projection("paper-main").consistent is True

    with sqlite3.connect(ledger.db_path) as connection:
        connection.execute(
            "UPDATE execution_accounts SET cash = '1' WHERE account_id = 'paper-main'"
        )
    verification = ledger.verify_projection("paper-main")
    assert verification.consistent is False
    assert verification.mismatches == ("cash",)
    assert verification.replayed.cash == Decimal("10318.5")


@pytest.mark.parametrize(
    ("field", "value"),
    [("quantity", "0"), ("price", "NaN"), ("fee", "-0.01")],
)
def test_invalid_economic_values_are_rejected_without_a_ledger_event(
    tmp_path, field, value
):
    ledger = ExecutionLedger(tmp_path / "ledger.sqlite3")
    ledger.register_account("paper-main", initial_cash="10000")
    values = {"quantity": "1", "price": "100", "fee": "0"}
    values[field] = value

    with pytest.raises(ValueError):
        ledger.apply_fill(_fill("fill-1", "buy", **values))

    with sqlite3.connect(ledger.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM execution_fill_ledger").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("payout", "expected_cash", "expected_pnl"),
    [("1", Decimal("1006"), Decimal("6")), ("0", Decimal("996"), Decimal("-4"))],
)
def test_binary_settlement_known_answer_and_projection(
    tmp_path, payout, expected_cash, expected_pnl
):
    ledger = ExecutionLedger(tmp_path / f"ledger-{payout}.sqlite3")
    ledger.register_account("paper-main", initial_cash="1000")
    ledger.apply_fill(_fill("fill-1", "buy", "10", "0.4", "0"))

    receipt = ledger.apply_settlement(_settlement("settlement-1", payout=payout))

    assert receipt.replayed is False
    assert receipt.payout_per_token == Decimal(payout)
    assert receipt.cash_after == expected_cash
    assert receipt.position_after == Decimal("0")
    assert receipt.gross_realized_delta == expected_pnl
    assert receipt.net_realized_delta == expected_pnl
    account = ledger.get_account("paper-main")
    assert account.cash == expected_cash
    assert account.gross_realized_pnl == expected_pnl
    assert account.net_realized_pnl == expected_pnl
    assert account.positions["AAPL"].quantity == Decimal("0")
    assert ledger.verify_projection("paper-main").consistent is True


def test_binary_settlement_replay_is_idempotent_and_conflicts_on_changed_payload(tmp_path):
    ledger = ExecutionLedger(tmp_path / "ledger.sqlite3")
    ledger.register_account("paper-main", initial_cash="1000")
    ledger.apply_fill(_fill("fill-1", "buy", "10", "0.4", "0"))
    command = _settlement("settlement-1", quantity="4", payout="1")

    first = ledger.apply_settlement(command)
    replay = ledger.apply_settlement(command)

    assert replay.replayed is True
    assert replay.sequence == first.sequence
    assert ledger.get_account("paper-main").cash == Decimal("1000")
    assert ledger.get_account("paper-main").positions["AAPL"].quantity == Decimal("6")
    assert ledger.verify_projection("paper-main").consistent is True

    with pytest.raises(FillConflict):
        ledger.apply_settlement(_settlement("settlement-1", quantity="4", payout="0"))


def test_binary_settlement_rejects_invalid_payout_and_excess_quantity_without_event(tmp_path):
    ledger = ExecutionLedger(tmp_path / "ledger.sqlite3")
    ledger.register_account("paper-main", initial_cash="1000")
    ledger.apply_fill(_fill("fill-1", "buy", "2", "0.4", "0"))

    with pytest.raises(ValueError, match="payout_per_token"):
        ledger.apply_settlement(_settlement("settlement-invalid", payout="0.5"))
    with pytest.raises(SettlementError, match="exceeds long position"):
        ledger.apply_settlement(_settlement("settlement-excess", quantity="3", payout="1"))

    with sqlite3.connect(ledger.db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM execution_fill_ledger WHERE event_type = 'settlement'"
        ).fetchone()[0] == 0
    assert ledger.get_account("paper-main").cash == Decimal("999.2")
    assert ledger.get_account("paper-main").positions["AAPL"].quantity == Decimal("2")
    assert ledger.verify_projection("paper-main").consistent is True
