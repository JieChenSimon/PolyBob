"""Tests for the data-quality / freshness gate."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from libs.quant.data_quality import (
    FreshnessPolicy,
    Verdict,
    check_completeness,
    check_freshness,
    check_schema,
    validate_record,
    worst,
)

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
POLICY = FreshnessPolicy(warn_after=timedelta(seconds=30), block_after=timedelta(minutes=5))


def _ago(**kw):
    return NOW - timedelta(**kw)


# --- freshness ------------------------------------------------------------


def test_fresh_data_is_ok():
    assert check_freshness(_ago(seconds=5), NOW, POLICY).verdict is Verdict.OK


def test_stale_data_degrades():
    assert check_freshness(_ago(seconds=90), NOW, POLICY).verdict is Verdict.DEGRADED


def test_very_stale_data_blocks():
    assert check_freshness(_ago(minutes=10), NOW, POLICY).verdict is Verdict.BLOCKED


def test_missing_timestamp_blocks():
    assert check_freshness(None, NOW, POLICY).verdict is Verdict.BLOCKED


def test_future_timestamp_blocks():
    # Clock skew / upstream look-ahead: source time after "now".
    assert check_freshness(NOW + timedelta(seconds=10), NOW, POLICY).verdict is Verdict.BLOCKED


def test_freshness_policy_rejects_inverted_thresholds():
    with pytest.raises(ValueError):
        FreshnessPolicy(warn_after=timedelta(minutes=5), block_after=timedelta(seconds=30))


# --- completeness & schema ------------------------------------------------


def test_completeness_blocks_on_missing_fields():
    result = check_completeness({"a": 1, "b": None}, ["a", "b", "c"])
    assert result.verdict is Verdict.BLOCKED
    assert "b" in result.detail and "c" in result.detail


def test_schema_blocks_on_wrong_type():
    result = check_schema({"price": "not-a-number"}, {"price": float})
    assert result.verdict is Verdict.BLOCKED


def test_schema_blocks_on_non_finite():
    result = check_schema({"price": float("nan")}, {"price": float})
    assert result.verdict is Verdict.BLOCKED


def test_schema_rejects_bool_as_int():
    result = check_schema({"size": True}, {"size": int})
    assert result.verdict is Verdict.BLOCKED


def test_schema_ok_for_valid_record():
    result = check_schema({"price": 1.5, "size": 3}, {"price": float, "size": int})
    assert result.verdict is Verdict.OK


# --- combined -------------------------------------------------------------


def test_worst_picks_most_severe():
    assert worst([Verdict.OK, Verdict.DEGRADED, Verdict.OK]) is Verdict.DEGRADED
    assert worst([Verdict.DEGRADED, Verdict.BLOCKED]) is Verdict.BLOCKED
    assert worst([]) is Verdict.OK


def test_validate_record_combines_all_checks():
    record = {
        "market_id": "m1",
        "mid_price": 0.51,
        "source_time": _ago(seconds=90).isoformat(),
    }
    report = validate_record(
        record,
        now=NOW,
        source_time_field="source_time",
        freshness=POLICY,
        required_fields=["market_id", "mid_price"],
        schema={"mid_price": float},
    )
    # Fresh-ish but stale -> degraded overall, not blocked.
    assert report.verdict is Verdict.DEGRADED
    assert not report.blocked
    assert report.reasons  # carries the degradation reason


def test_validate_record_blocks_when_any_check_blocks():
    record = {"market_id": "m1", "mid_price": None, "source_time": _ago(seconds=5).isoformat()}
    report = validate_record(
        record,
        now=NOW,
        source_time_field="source_time",
        freshness=POLICY,
        required_fields=["market_id", "mid_price"],
    )
    assert report.blocked
