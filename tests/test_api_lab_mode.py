from types import SimpleNamespace

import apps.api.main as api


def test_lab_auto_trader_disabled_does_not_initialize_engine(monkeypatch):
    monkeypatch.setattr(
        api,
        "get_settings",
        lambda: SimpleNamespace(enable_lab_auto_trader=False, product_mode="personal_workbench"),
    )
    api.trading_engine = None

    status = api.get_lab_trading_status()

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
