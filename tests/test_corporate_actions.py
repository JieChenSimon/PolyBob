from __future__ import annotations

import datetime as dt

import pytest

from libs.data import store
from libs.data.corporate_actions import (
    CorporateAction,
    CorporateActionType,
    raw_price_return,
)
from libs.quant import edge_backtest
from libs.quant.edge import Direction


NOW = dt.datetime(2026, 6, 1, tzinfo=dt.UTC)


@pytest.fixture(autouse=True)
def _isolated_store(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "STORE_ROOT", tmp_path / "store")


def _split() -> CorporateAction:
    return CorporateAction(
        instrument="X",
        effective_at=dt.date(2026, 3, 3),
        action_type=CorporateActionType.SPLIT,
        ratio=2.0,
        source="test_exchange_notice",
    )


def test_corporate_actions_have_typed_time_and_price_semantics():
    contract = store.CORPORATE_ACTIONS.contract()
    assert contract["effective_at"] == store.EVENT_DATE
    assert contract["observed_at"] == store.FETCHED_AT
    assert contract["price_basis"] == "action_declared"
    assert "action_type" in contract["value_columns"]


def test_two_for_one_split_does_not_create_a_false_loss():
    assert raw_price_return(
        100.0,
        50.0,
        [_split()],
        entry_date=dt.date(2026, 3, 2),
        exit_date=dt.date(2026, 3, 3),
    ) == pytest.approx(0.0)


def test_invalid_split_ratio_is_rejected():
    action = CorporateAction(
        instrument="X",
        effective_at=dt.date(2026, 3, 3),
        action_type=CorporateActionType.SPLIT,
        ratio=0.0,
        source="test",
    )
    with pytest.raises(ValueError, match="split ratio"):
        action.validate()


def test_backtest_applies_split_once_to_raw_prices():
    store.write(
        store.DAILY_BARS,
        "X",
        [
            {"symbol": "X", store.EVENT_DATE: "2026-03-02", "close": 100.0,
             "source": "test", "price_basis": "raw"},
            {"symbol": "X", store.EVENT_DATE: "2026-03-03", "close": 50.0,
             "source": "test", "price_basis": "raw"},
        ],
        fetched_at=dt.datetime(2026, 3, 1, tzinfo=dt.UTC),
    )
    store.write(
        store.CORPORATE_ACTIONS,
        "X",
        [_split().to_store_row()],
        fetched_at=dt.datetime(2026, 3, 1, tzinfo=dt.UTC),
    )

    result = edge_backtest.replay_events(
        [("X", "2026-03-02")],
        direction=Direction.LONG,
        hold_sessions=1,
        benchmark=None,
        cost_bps=0.0,
        as_of=NOW,
        t_hurdle=3.0,
    )

    assert result.trades[0].gross_return == pytest.approx(0.0)
    assert result.dropped_ambiguous_corporate_action == 0


def test_backtest_refuses_unknown_price_basis_across_a_split():
    store.write(
        store.DAILY_BARS,
        "X",
        [
            {"symbol": "X", store.EVENT_DATE: "2026-03-02", "close": 100.0,
             "source": "test", "price_basis": "provider_unknown"},
            {"symbol": "X", store.EVENT_DATE: "2026-03-03", "close": 50.0,
             "source": "test", "price_basis": "provider_unknown"},
        ],
        fetched_at=dt.datetime(2026, 3, 1, tzinfo=dt.UTC),
    )
    store.write(
        store.CORPORATE_ACTIONS,
        "X",
        [_split().to_store_row()],
        fetched_at=dt.datetime(2026, 3, 1, tzinfo=dt.UTC),
    )

    result = edge_backtest.replay_events(
        [("X", "2026-03-02")],
        direction=Direction.LONG,
        hold_sessions=1,
        benchmark=None,
        cost_bps=0.0,
        as_of=NOW,
        t_hurdle=3.0,
    )

    assert result.trades == []
    assert result.dropped_ambiguous_corporate_action == 1
