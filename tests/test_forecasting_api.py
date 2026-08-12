from fastapi.testclient import TestClient

from apps.api.main import app


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
