import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import apps.api.main as api


PORTFOLIO_NOTE = "Portfolio ledger not configured"


class DummyStrategyManager:
    def list_templates(self):
        return [{"family": "spread"}]

    def list_instances(self):
        return [{"status": "running"}]


class DummyIntentService:
    def list_intents(self):
        return []


class DummyBasketExecutor:
    def list_baskets(self):
        return []


class DummyOnchainMonitor:
    def get_summary(self):
        return {
            "alert_count": 0,
            "critical_alerts": 0,
            "recent_cex_flow_usd": 0.0,
        }


@pytest.fixture
def api_dependencies(monkeypatch):
    api.clear_api_response_cache()

    async def collect_markets(limit=36):
        return []

    monkeypatch.setattr(
        api,
        "get_settings",
        lambda: SimpleNamespace(
            enable_lab_auto_trader=False,
            enable_lab_backtest=False,
            product_mode="personal_workbench",
        ),
    )
    monkeypatch.setattr(api, "collect_dashboard_markets", collect_markets)
    monkeypatch.setattr(api, "require_strategy_manager", lambda: DummyStrategyManager())
    monkeypatch.setattr(api, "require_intent_execution_service", lambda: DummyIntentService())
    monkeypatch.setattr(api, "require_basket_executor", lambda: DummyBasketExecutor())
    monkeypatch.setattr(api, "require_onchain_monitor", lambda: DummyOnchainMonitor())
    api.trading_engine = None


@pytest.mark.asyncio
async def test_overview_marks_missing_portfolio_ledger_as_not_configured(api_dependencies):
    overview = await api.get_overview()

    assert overview["risk"]["portfolio_status"] == "not_configured"
    assert overview["execution"]["portfolio_status"] == "not_configured"
    assert overview["risk"]["alert_level"] == "not_configured"
    assert overview["risk"]["net_exposure"] is None
    assert overview["risk"]["estimated_leverage"] is None
    assert overview["execution"]["pnl"] is None
    assert overview["execution"]["pnl_pct"] is None
    assert any(PORTFOLIO_NOTE in note for note in overview["risk"]["notes"])


@pytest.mark.asyncio
async def test_risk_summary_does_not_report_zero_risk_without_portfolio_ledger(api_dependencies):
    summary = await api.get_risk_summary()

    assert summary["portfolio_status"] == "not_configured"
    assert summary["alert_level"] == "not_configured"
    assert summary["net_exposure"] is None
    assert summary["estimated_leverage"] is None
    assert summary["pnl"] is None
    assert summary["pnl_pct"] is None
    assert any(PORTFOLIO_NOTE in note for note in summary["notes"])


@pytest.mark.asyncio
async def test_current_trading_start_keeps_lab_guard(monkeypatch):
    monkeypatch.setattr(
        api,
        "get_settings",
        lambda: SimpleNamespace(
            enable_lab_auto_trader=False,
            enable_lab_backtest=False,
            product_mode="personal_workbench",
        ),
    )
    api.trading_engine = None

    with pytest.raises(HTTPException) as exc_info:
        await api.start_trading()

    assert exc_info.value.status_code == 403
    assert api.trading_engine is None


@pytest.mark.asyncio
async def test_sample_backtest_keeps_lab_guard(monkeypatch):
    monkeypatch.setattr(
        api,
        "get_settings",
        lambda: SimpleNamespace(
            enable_lab_auto_trader=False,
            enable_lab_backtest=False,
            product_mode="personal_workbench",
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        await api.backtest()

    assert exc_info.value.status_code == 403
    assert "Sample backtest is a lab module" in exc_info.value.detail


@pytest.mark.asyncio
async def test_archived_api_server_cannot_bypass_lab_guard():
    module_path = Path(__file__).resolve().parents[1] / "services" / "api_server" / "main.py"
    spec = importlib.util.spec_from_file_location("archived_api_server_main", module_path)
    archived_api = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(archived_api)

    route_paths = {route.path for route in archived_api.app.routes}
    assert "/api/trading/start" not in route_paths
    assert "/api/trading/status" not in route_paths
    assert "/api/trading/performance" not in route_paths

    payload = await archived_api.root()
    assert payload["status"] == "archived"
    assert "no longer exposes trading API routes" in payload["message"]
