import datetime as dt
from types import SimpleNamespace

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api import forecasting_api
from libs.forecasting.state_store import ForecastInstrumentStore
from libs.forecasting.contracts import AssetClass, BarInterval, CanonicalBar, CanonicalBarFrame


def test_forecasting_status_is_fail_closed():
    response = TestClient(app).get("/api/forecasting/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is False
    assert payload["trade_permission"] is False
    assert payload["promotion_status"] == "lab_only"


def test_forecast_endpoint_does_not_fetch_while_lab_is_disabled():
    response = TestClient(app).get(
        "/api/forecasting/forecast",
        params={"symbol": "0xabc", "domain": "prediction_market"},
    )
    assert response.status_code == 409
    assert "disabled" in response.json()["detail"]


class _ReadyLab:
    config = SimpleNamespace(enabled=True)

    @staticmethod
    def readiness(verify_hashes=False):
        return {
            "enabled": True,
            "ready": True,
            "loaded": False,
            "reason": None,
        }


def test_instrument_opt_in_is_persistent_and_never_grants_trade_permission(
    tmp_path, monkeypatch
):
    store = ForecastInstrumentStore(tmp_path / "forecast.sqlite3")
    monkeypatch.setattr(forecasting_api, "get_instrument_store", lambda: store)
    monkeypatch.setattr(forecasting_api, "get_lab", lambda: _ReadyLab())
    client = TestClient(app)

    before = client.get("/api/forecasting/instruments/us_equity/AAPL")
    assert before.status_code == 200
    assert before.json()["enabled"] is False

    enabled = client.put(
        "/api/forecasting/instruments/us_equity/AAPL",
        json={"enabled": True, "horizon": 10},
    )
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True
    assert enabled.json()["trade_permission"] is False
    assert ForecastInstrumentStore(store.db_path).get("us_equity", "AAPL").horizon == 10

    disabled = client.put(
        "/api/forecasting/instruments/us_equity/AAPL",
        json={"enabled": False, "horizon": 10},
    )
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert ForecastInstrumentStore(store.db_path).get("us_equity", "AAPL").enabled is False


def test_run_rejects_unenabled_instrument_before_fetch(tmp_path, monkeypatch):
    store = ForecastInstrumentStore(tmp_path / "forecast.sqlite3")
    monkeypatch.setattr(forecasting_api, "get_instrument_store", lambda: store)
    monkeypatch.setattr(forecasting_api, "get_lab", lambda: _ReadyLab())
    monkeypatch.setattr(
        forecasting_api,
        "_frame",
        lambda *_: (_ for _ in ()).throw(AssertionError("data fetch must not run")),
    )

    response = TestClient(app).post(
        "/api/forecasting/runs",
        json={"symbol": "AAPL", "domain": "us_equity", "horizon": 5},
    )
    assert response.status_code == 409
    assert "enable this instrument first" in response.json()["detail"]


def test_input_state_is_descriptive_and_preserves_provenance():
    bars = tuple(
        CanonicalBar(
            timestamp=dt.datetime(2026, 1, 1, tzinfo=dt.UTC) + dt.timedelta(days=index),
            open=100 + index,
            high=102 + index,
            low=99 + index,
            close=101 + index,
            volume=1_000 + index * 10,
        )
        for index in range(65)
    )
    frame = CanonicalBarFrame(
        instrument_id="TEST",
        asset_class=AssetClass.US_EQUITY,
        venue="TEST",
        interval=BarInterval.ONE_DAY,
        source="fixture",
        fetched_at=dt.datetime.now(dt.UTC),
        bars=bars,
    )

    state = forecasting_api._input_state(frame)

    assert state["interpretation"] == "descriptive_not_causal"
    assert state["return_5d"] == bars[-1].close / bars[-6].close - 1
    assert state["return_20d"] == bars[-1].close / bars[-21].close - 1
    assert state["realized_volatility_20d"] is not None
    assert state["drawdown_from_60d_high"] == 0
    assert state["volume_ratio_5d_vs_20d"] is not None
    assert len(state["history"]) == 40
    assert state["history"][-1]["close"] == bars[-1].close
