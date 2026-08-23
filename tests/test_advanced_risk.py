import pytest

from libs.quant.advanced_risk import analyze_tca, certify_adapter, stress_portfolio


def _fills(n=30):
    return [{"execution_price": 101.0, "reference_price": 100.0, "size": 1.0, "fee": 0.01, "depth": 100.0} for _ in range(n)]


def test_tca_is_unknown_until_sample_and_depth_budgets_are_met():
    assert analyze_tca(_fills(2), min_samples=3).status == "unknown"
    report = analyze_tca(_fills(), min_samples=30)
    assert report.status == "calibrated"
    assert report.mean_slippage_bps == pytest.approx(100.0)
    assert report.capacity_notional == 10.0


def test_stress_has_replayable_attribution_and_baseline():
    result = stress_portfolio({"BTC": [0.1, 0.0], "SPY": [0.02, 0.0]}, {"BTC": 0.75, "SPY": 0.25}, {"BTC": -0.2, "SPY": -0.1})
    assert result.status == "tested"
    assert set(result.attribution) == {"BTC", "SPY"}
    assert result.worst_case_return <= result.portfolio_return


def test_adapter_cannot_enable_before_all_lifecycle_checks():
    blocked = certify_adapter({"submit": True, "fill": True})
    assert blocked.status == "blocked"
    assert "cancel" in blocked.missing
    certified = certify_adapter({name: True for name in ("submit", "fill", "cancel", "disconnect", "reconnect", "idempotency")})
    assert certified.status == "certified"
