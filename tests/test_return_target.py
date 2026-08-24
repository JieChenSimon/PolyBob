from datetime import UTC, datetime, timedelta

import pytest

from libs.quant.return_target import evaluate_return_target, monthly_returns


def test_monthly_returns_are_calendar_aligned():
    points = [
        {"ts": datetime(2025, 1, 1, tzinfo=UTC), "equity": 100.0},
        {"ts": datetime(2025, 1, 31, tzinfo=UTC), "equity": 120.0},
        {"ts": datetime(2025, 2, 1, tzinfo=UTC), "equity": 120.0},
        {"ts": datetime(2025, 2, 28, tzinfo=UTC), "equity": 144.0},
    ]
    result = monthly_returns(points)
    assert result["2025-01"] == pytest.approx(0.2)
    assert result["2025-02"] == pytest.approx(0.2)


def test_return_target_is_unknown_before_twelve_complete_months():
    start = datetime(2025, 1, 1, tzinfo=UTC)
    points = [{"ts": start + timedelta(days=30 * i), "equity": 100.0 + i}
              for i in range(6)]
    decision = evaluate_return_target(points)
    assert decision.status == "UNKNOWN"
    assert "complete calendar months" in decision.reason


def test_return_target_requires_both_annualized_and_monthly_thresholds():
    points = []
    for month in range(13):
        points.append({"ts": datetime(2024 + (month // 12), (month % 12) + 1, 1, tzinfo=UTC),
                       "equity": 100.0 + month})
        points.append({"ts": datetime(2024 + ((month + 1) // 12), ((month + 1) % 12) + 1, 1, tzinfo=UTC),
                       "equity": 100.0 + month})
    decision = evaluate_return_target(points)
    assert decision.status == "FAIL"
    assert decision.annualized_return is not None
