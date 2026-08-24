from datetime import date, timedelta

import pandas as pd

from libs.quant.funding_readiness import assess_funding_frame, research_symbols


def _frame(n: int, *, start: date = date(2024, 1, 1), source: str = "test") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "event_date": [start + timedelta(days=i) for i in range(n)],
            "rate": [0.0001] * n,
            "source": [source] * n,
        }
    )


def test_short_history_is_blocked():
    result = assess_funding_frame("BTC-USDT-SWAP", _frame(90))
    assert result.status == "BLOCKED"
    assert "observations<252" in result.reasons
    assert result.oos_folds == 2


def test_four_folds_without_calendar_span_is_blocked():
    result = assess_funding_frame("BTC-USDT-SWAP", _frame(252, start=date(2024, 1, 1)))
    assert result.status == "BLOCKED"
    assert "span_days<365" in result.reasons


def test_sufficient_history_is_ready():
    result = assess_funding_frame("BTC-USDT-SWAP", _frame(400, start=date(2023, 1, 1)))
    assert result.status == "READY"
    assert result.oos_folds == 4
    assert result.sources == ("test",)


def test_missing_source_is_unknown_not_ready():
    frame = _frame(400, start=date(2023, 1, 1)).drop(columns=["source"])
    result = assess_funding_frame("BTC-USDT-SWAP", frame)
    assert result.status == "UNKNOWN"
    assert "missing_required_columns" in result.reasons


def test_blocked_report_has_no_research_symbols():
    assert research_symbols({"status": "BLOCKED", "ready_symbols": ["BTC-USDT-SWAP"]}) == ()


def test_ready_report_allows_only_ready_report_symbols():
    assert research_symbols({"status": "READY", "ready_symbols": ["BTC-USDT-SWAP"]}) == (
        "BTC-USDT-SWAP",
    )
