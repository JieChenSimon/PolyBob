from __future__ import annotations

import datetime as dt

import pytest

from libs.data.trading_calendar import (
    CRYPTO_24X7,
    XNYS_2026,
    XSHG_2026,
    CalendarCoverageError,
)


def test_crypto_calendar_includes_weekends():
    assert CRYPTO_24X7.sessions_after(dt.date(2026, 8, 14), 2) == (
        dt.date(2026, 8, 15),
        dt.date(2026, 8, 16),
    )


def test_nyse_calendar_skips_observed_independence_day_and_weekend():
    assert XNYS_2026.sessions_after(dt.date(2026, 7, 2), 1) == (
        dt.date(2026, 7, 6),
    )


def test_sse_calendar_skips_exchange_published_autumn_closure():
    assert XSHG_2026.sessions_after(dt.date(2026, 9, 24), 1) == (
        dt.date(2026, 9, 28),
    )


def test_bounded_calendar_refuses_to_guess_an_unaudited_year():
    with pytest.raises(CalendarCoverageError, match="ends at 2026-12-31"):
        XNYS_2026.sessions_after(dt.date(2026, 12, 31), 1)


def test_exchange_calendar_exposes_a_machine_readable_contract():
    contract = XSHG_2026.contract()
    assert contract["quality"] == "official_exchange_schedule"
    assert contract["coverage_start"] == "2026-01-01"
    assert contract["coverage_end"] == "2026-12-31"
    assert str(contract["source"]).startswith("https://www.sse.com.cn/")
