from fastapi.testclient import TestClient

from apps.api.main import app


def test_capability_matrix_is_fail_closed_and_has_explicit_boundaries():
    assert "交易自动化系统" not in app.description
    response = TestClient(app).get("/api/capabilities")
    assert response.status_code == 200
    payload = response.json()
    assert payload["product_mode"] == "personal_workbench"
    assert payload["trade_execution_ready"] is False

    rows = payload["rows"]
    assert {row["tier"] for row in rows} == {"core", "lab", "archive"}
    assert all(row["trade_permission"] is False for row in rows)
    assert all(row["truth"] for row in rows)
    assert all(row["routes"] or row["api_prefixes"] for row in rows)

    by_id = {row["capability_id"]: row for row in rows}
    assert by_id["paper_execution"]["state"] == "blocked"
    assert by_id["auto_trader"]["tier"] == "archive"
    assert by_id["manual_journal"]["state"] == "degraded"
