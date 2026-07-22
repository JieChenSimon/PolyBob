import pytest

from libs.crypto.discovery.models import Evidence
from libs.crypto.discovery.scoring import (
    CASHOUT_WEIGHTS,
    PUMP_WEIGHTS,
    derive_market_features,
    score_candidate,
)


def observed(name: str, value: float) -> Evidence:
    return Evidence(
        name=name,
        value=value,
        status="observed",
        weight=1.0,
        provider="test",
    )


def test_weight_matrices_sum_to_one_for_every_horizon():
    assert all(sum(weights.values()) == pytest.approx(1.0) for weights in PUMP_WEIGHTS.values())
    assert all(
        sum(weights.values()) == pytest.approx(1.0) for weights in CASHOUT_WEIGHTS.values()
    )


def test_all_three_horizons_are_returned():
    result = score_candidate(
        [
            observed("floor", 0.8),
            observed("washout", 0.7),
            observed("control", 0.9),
            observed("accumulation", 0.8),
            observed("historical_operator_strength", 0.6),
            observed("futures_squeeze", 0.7),
        ]
    )

    assert set(result.pump_potential) == {"7d", "30d", "90d"}
    assert set(result.cashout_risk) == {"7d", "30d", "90d"}


def test_missing_evidence_reduces_coverage_without_becoming_zero():
    full = score_candidate(
        [
            observed(name, 0.5)
            for name in (
                "floor",
                "washout",
                "control",
                "accumulation",
                "historical_operator_strength",
                "futures_squeeze",
            )
        ]
    )
    partial = score_candidate([observed("floor", 0.5)])

    assert partial.coverage < full.coverage
    assert partial.pump_potential["30d"].value == pytest.approx(50.0)


def test_unavailable_evidence_is_not_treated_as_zero():
    result = score_candidate(
        [
            observed("floor", 0.8),
            Evidence(
                name="washout",
                value=0.0,
                status="unavailable",
                provider="test",
            ),
        ]
    )

    assert result.pump_potential["30d"].value == pytest.approx(80.0)


def test_unsupported_evidence_is_excluded_from_coverage_denominator():
    base = score_candidate(
        [
            observed("floor", 0.8),
            observed("washout", 0.7),
            observed("control", 0.9),
            observed("accumulation", 0.8),
            observed("historical_operator_strength", 0.6),
            observed("audit_risk", 0.1),
            observed("liquidity_risk", 0.1),
            observed("abnormal_turnover", 0.2),
        ]
    )
    adjusted = score_candidate(
        [
            observed("floor", 0.8),
            observed("washout", 0.7),
            observed("control", 0.9),
            observed("accumulation", 0.8),
            observed("historical_operator_strength", 0.6),
            observed("audit_risk", 0.1),
            observed("liquidity_risk", 0.1),
            observed("abnormal_turnover", 0.2),
            Evidence(name="futures_squeeze", status="unsupported", provider="test"),
            Evidence(name="crowded_longs", status="unsupported", provider="test"),
            Evidence(name="unlock_risk", status="unsupported", provider="test"),
        ]
    )

    assert base.coverage < 0.70
    assert adjusted.coverage >= 0.70
    assert adjusted.pump_potential["30d"].value == pytest.approx(base.pump_potential["30d"].value)


def test_concentration_raises_potential_and_cashout_risk_separately():
    low = score_candidate(
        [observed("control", 0.2), observed("dev_concentration", 0.2)]
    )
    high = score_candidate(
        [observed("control", 0.9), observed("dev_concentration", 0.9)]
    )

    assert high.pump_potential["30d"].value > low.pump_potential["30d"].value
    assert high.cashout_risk["30d"].value > low.cashout_risk["30d"].value


def test_deep_retracement_after_real_rally_raises_floor_washout_and_operator_strength():
    closes = [1.0, 1.1, 1.3, 1.8, 2.6, 3.2, 2.7, 2.2, 1.8, 1.55, 1.45, 1.42, 1.44, 1.46]
    volumes = [100, 120, 180, 400, 900, 1200, 800, 500, 320, 220, 160, 130, 135, 145]

    features = derive_market_features(
        closes=closes,
        volumes=volumes,
        market_cap_percentile=0.1,
        top10_holder_percent=82.0,
        smart_money_inflow_percentile=0.8,
        buy_volume=600.0,
        sell_volume=400.0,
    )

    assert features["floor"] > 0.65
    assert features["washout"] > 0.5
    assert features["historical_operator_strength"] > 0.5
    assert features["control"] > 0.8
    assert features["accumulation"] > 0.7
