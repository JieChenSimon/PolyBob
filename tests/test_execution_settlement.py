"""Known-answer tests for binary settlement events in the authoritative ledger."""

from decimal import Decimal

import pytest

from libs.db.execution_ledger import (
    ExecutionLedger,
    FillCommand,
    FillConflict,
    SettlementCommand,
    SettlementError,
)


def _ledger(tmp_path: object) -> ExecutionLedger:
    ledger = ExecutionLedger(tmp_path / "settlement.sqlite3")
    ledger.register_account("paper-main", initial_cash="100")
    ledger.apply_fill(FillCommand(
        fill_id="entry-1", account_id="paper-main", order_id="order-1",
        instrument_id="BTC5M:1:UP", side="buy", quantity="10", price="0.4",
        fee="0", executed_at="2026-08-25T00:00:00+00:00",
    ))
    return ledger


def _settlement(payout: str = "1") -> SettlementCommand:
    return SettlementCommand(
        settlement_id="settle-1", account_id="paper-main", market_id="market-1",
        instrument_id="BTC5M:1:UP", quantity="10", payout_per_token=payout,
        settled_at="2026-08-25T00:05:00+00:00",
    )


def test_winning_settlement_is_atomic_idempotent_and_replayable(tmp_path):
    ledger = _ledger(tmp_path)
    first = ledger.apply_settlement(_settlement("1"))
    replay = ledger.apply_settlement(_settlement("1"))

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.sequence == first.sequence
    assert first.cash_after == Decimal("106")
    assert first.position_after == Decimal("0")
    assert first.gross_realized_delta == Decimal("6")
    account = ledger.get_account("paper-main")
    assert account.cash == Decimal("106")
    assert account.positions["BTC5M:1:UP"].quantity == Decimal("0")
    assert ledger.replay("paper-main").cash == Decimal("106")
    assert ledger.verify_projection("paper-main").consistent is True


def test_losing_settlement_pays_zero_without_fee_or_sell_fill(tmp_path):
    ledger = _ledger(tmp_path)
    receipt = ledger.apply_settlement(_settlement("0"))
    assert receipt.cash_after == Decimal("96")
    assert receipt.gross_realized_delta == Decimal("-4")
    assert ledger.get_account("paper-main").total_fees == Decimal("0")
    assert ledger.verify_projection("paper-main").consistent is True


def test_settlement_rejects_invalid_payout_excess_quantity_and_conflict(tmp_path):
    ledger = _ledger(tmp_path)
    with pytest.raises(ValueError, match="exactly 0 or 1"):
        ledger.apply_settlement(_settlement("0.5"))
    with pytest.raises(SettlementError, match="exceeds long position"):
        ledger.apply_settlement(SettlementCommand(
            settlement_id="too-much", account_id="paper-main", market_id="market-1",
            instrument_id="BTC5M:1:UP", quantity="11", payout_per_token="1",
            settled_at="2026-08-25T00:05:00+00:00",
        ))
    ledger.apply_settlement(_settlement("1"))
    with pytest.raises(FillConflict):
        ledger.apply_settlement(SettlementCommand(
            **{**_settlement("0").__dict__, "payout_per_token": "0"}
        ))
