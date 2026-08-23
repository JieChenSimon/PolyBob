from types import SimpleNamespace

import apps.api.main as api
import pytest


async def test_lab_auto_trader_disabled_does_not_initialize_engine(monkeypatch):
    monkeypatch.setattr(
        api,
        "get_settings",
        lambda: SimpleNamespace(enable_lab_auto_trader=False, product_mode="personal_workbench"),
    )
    api.trading_engine = None

    status = await api.get_lab_trading_status()

    assert status["enabled"] is False
    assert status["mode"] == "lab_disabled"
    assert status["running"] is False
    assert api.trading_engine is None


def test_service_health_marks_auto_trader_as_lab_disabled(monkeypatch):
    monkeypatch.setattr(
        api,
        "get_settings",
        lambda: SimpleNamespace(enable_lab_auto_trader=False, product_mode="personal_workbench"),
    )
    api.trading_engine = None

    services = api.get_service_health()
    auto_trader = next(service for service in services if service["name"] == "auto_trader_demo")

    assert auto_trader["tier"] == "lab"
    assert auto_trader["status"] == "disabled"
    assert api.trading_engine is None


def test_paper_execution_is_blocked_without_explicit_lab_switch(monkeypatch):
    monkeypatch.setattr(
        api,
        "get_settings",
        lambda: SimpleNamespace(enable_lab_paper_execution=False),
    )

    with pytest.raises(api.HTTPException) as error:
        api.require_lab_paper_execution()

    assert error.value.status_code == 403
    assert error.value.detail["capability"] == "paper_execution"


def test_portfolio_risk_snapshot_does_not_substitute_zeroes():
    snapshot = api.get_portfolio_risk_snapshot()

    assert snapshot["portfolio_status"] == "not_configured"
    assert snapshot["net_exposure"] is None
    assert snapshot["estimated_leverage"] is None
    assert snapshot["total_value"] is None
    assert snapshot["pnl"] is None
    assert snapshot["pnl_pct"] is None
    assert "not configured" in snapshot["notes"][0]


def test_not_configured_portfolio_alert_is_not_nominal():
    snapshot = api.get_portfolio_risk_snapshot()

    alert_level = api.get_portfolio_alert_level(snapshot, critical_alerts=0, watch_condition=False)

    assert alert_level == "not_configured"
