"""API contract tests for /api/simulation endpoints (frontend envelope shapes)."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import apps.api.main as api
from services.simulation import SimulationService


@pytest.fixture
def sim_api(monkeypatch, tmp_path):
    """Real SimulationService on a tmp DB, injected into the app (no lifespan)."""
    service = SimulationService(tmp_path / "sim.sqlite3", equity_poll_seconds=3600)
    monkeypatch.setattr(api, "simulation_service", service)
    # TestClient without a context manager does not run the lifespan, so no
    # network-bound services start; only the injected simulation service is used.
    return TestClient(api.app), service


CREATE_PAYLOAD = {
    "name": "sim one",
    "strategy_id": "spread_reversion_v1",
    "universe": ["m1"],
    "initial_capital": 5_000.0,
    "config": {"cooldown_seconds": 0.0, "impact_coefficient": 0.0},
}


def create_run(client) -> str:
    response = client.post("/api/simulation/runs", json=CREATE_PAYLOAD)
    assert response.status_code == 200
    run = response.json()["run"]
    assert run["status"] == "paused"
    assert run["cash"] == 5_000.0
    return run["run_id"]


def test_create_and_list_runs_envelope(sim_api):
    client, _ = sim_api
    run_id = create_run(client)

    response = client.get("/api/simulation/runs")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["runs"], list)
    run = next(item for item in body["runs"] if item["run_id"] == run_id)
    assert run["strategy_id"] == "spread_reversion_v1"
    assert run["universe"] == ["m1"]
    assert run["initial_capital"] == 5_000.0
    # Headline metrics ride along with each run.
    assert "metrics" in run
    assert run["metrics"]["trade_count"] == 0
    assert run["metrics"]["win_rate"] is None


def test_create_run_validation_errors(sim_api):
    client, _ = sim_api
    bad = dict(CREATE_PAYLOAD, strategy_id="does_not_exist")
    assert client.post("/api/simulation/runs", json=bad).status_code == 400
    bad = dict(CREATE_PAYLOAD, universe=[])
    assert client.post("/api/simulation/runs", json=bad).status_code == 400
    bad = dict(CREATE_PAYLOAD, initial_capital=0)
    assert client.post("/api/simulation/runs", json=bad).status_code == 400


def test_run_detail_envelope_and_downsampled_curve(sim_api):
    client, service = sim_api
    run_id = create_run(client)

    base = datetime(2026, 7, 1, tzinfo=UTC)
    for offset in range(700):
        service.store.append_equity_point(
            run_id,
            equity=5_000.0 + offset,
            cash=5_000.0,
            gross_exposure=0.0,
            ts=(base + timedelta(minutes=offset)).isoformat(),
        )

    response = client.get(f"/api/simulation/runs/{run_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["run"]["run_id"] == run_id
    assert set(body) == {"run", "metrics", "equity_curve", "positions", "trades"}
    assert body["positions"] == []
    assert body["trades"] == []
    # Server-side cap at 500 points, endpoints keep first/last.
    curve = body["equity_curve"]
    assert 2 <= len(curve) <= 500
    assert set(curve[0]) == {"ts", "equity"}
    assert curve[0]["equity"] == 5_000.0
    assert curve[-1]["equity"] == 5_699.0
    assert body["metrics"]["total_return"] == pytest.approx(699.0 / 5_000.0)


def test_unknown_run_returns_404(sim_api):
    client, _ = sim_api
    assert client.get("/api/simulation/runs/sim_nope").status_code == 404
    assert client.post("/api/simulation/runs/sim_nope/start").status_code == 404
    assert client.post("/api/simulation/runs/sim_nope/pause").status_code == 404
    assert client.post("/api/simulation/runs/sim_nope/stop").status_code == 404
    assert client.post("/api/simulation/runs/sim_nope/feedback").status_code == 404


def test_lifecycle_endpoints_and_invalid_transitions(sim_api):
    client, _ = sim_api
    run_id = create_run(client)

    # paused -> pause is invalid.
    assert client.post(f"/api/simulation/runs/{run_id}/pause").status_code == 409

    response = client.post(f"/api/simulation/runs/{run_id}/start")
    assert response.status_code == 200
    assert response.json()["run"]["status"] == "running"

    # running -> start is invalid.
    assert client.post(f"/api/simulation/runs/{run_id}/start").status_code == 409

    response = client.post(f"/api/simulation/runs/{run_id}/pause")
    assert response.json()["run"]["status"] == "paused"

    response = client.post(f"/api/simulation/runs/{run_id}/stop")
    assert response.json()["run"]["status"] == "stopped"

    # stopped is terminal.
    assert client.post(f"/api/simulation/runs/{run_id}/start").status_code == 409
    assert client.post(f"/api/simulation/runs/{run_id}/stop").status_code == 409


def test_feedback_endpoint_reports_guardrail(sim_api):
    client, service = sim_api
    payload = dict(CREATE_PAYLOAD, strategy_id="signal_fusion")
    response = client.post("/api/simulation/runs", json=payload)
    run_id = response.json()["run"]["run_id"]

    # No closed trades yet: guardrail refuses, endpoint still 200 with reason.
    response = client.post(f"/api/simulation/runs/{run_id}/feedback")
    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == run_id
    assert body["applied"] is False
    assert "insufficient closed trades" in body["reason"]
    assert body["weight_deltas"] == {}

    # With enough closed trades the endpoint returns capped weight deltas.
    service.store.update_run(
        run_id,
        config={**service.store.get_run(run_id).config, "feedback_min_closed_trades": 3},
    )
    # Keep the in-memory record in sync with the tightened guardrail.
    service._active[run_id].record = service.store.get_run(run_id)
    for realized in (1.0, 2.0, 3.0, None):
        service.store.append_trade(
            run_id,
            instrument_id="m1",
            side="sell" if realized is not None else "buy",
            size=1.0,
            price=1.0,
            fee=0.0,
            slippage=0.0,
            signal_meta={"signals": ["rsi"]},
            realized_pnl=realized,
        )
    response = client.post(f"/api/simulation/runs/{run_id}/feedback")
    assert response.status_code == 200
    body = response.json()
    assert body["applied"] is True
    assert body["weight_deltas"]
    for delta in body["weight_deltas"].values():
        assert abs(delta) <= 0.05 + 1e-6


def test_simulation_service_not_ready_returns_503(monkeypatch):
    monkeypatch.setattr(api, "simulation_service", None)
    client = TestClient(api.app)
    assert client.get("/api/simulation/runs").status_code == 503
    assert client.post("/api/simulation/runs", json=CREATE_PAYLOAD).status_code == 503


def test_list_presets_envelope(sim_api):
    client, _ = sim_api
    response = client.get("/api/simulation/presets")
    assert response.status_code == 200
    presets = response.json()["presets"]
    assert len(presets) >= 5
    ids = {p["id"] for p in presets}
    assert {"single_instrument_deep", "conservative_stress", "pair_arbitrage_focus"} <= ids
    for p in presets:
        # every preset must reference an executable strategy factory
        assert p["strategy_id"] in {"signal_fusion", "spread_reversion_v1", "spread_arbitrage_v1"}
        assert p["name"]["zh"] and p["name"]["en"]
        assert isinstance(p["suggested_universe"], list) and p["suggested_universe"]


def test_create_run_from_preset_applies_defaults(sim_api):
    client, _ = sim_api
    # No strategy_id/universe: preset supplies them.
    response = client.post(
        "/api/simulation/runs",
        json={"preset_id": "conservative_stress", "initial_capital": 8_000.0},
    )
    assert response.status_code == 200
    run = response.json()["run"]
    assert run["strategy_id"] == "signal_fusion"
    assert run["cash"] == 8_000.0
    # preset config landed
    assert run["config"]["position_fraction"] == 0.02
    assert run["config"]["mid_penalty_bps"] == 25.0


def test_create_run_preset_overridden_by_request(sim_api):
    client, _ = sim_api
    response = client.post(
        "/api/simulation/runs",
        json={
            "preset_id": "single_instrument_deep",
            "name": "my custom run",
            "universe": ["real_market_42"],
            "config": {"position_fraction": 0.07},
        },
    )
    assert response.status_code == 200
    run = response.json()["run"]
    assert run["name"] == "my custom run"
    assert run["universe"] == ["real_market_42"]  # operator override wins
    assert run["config"]["position_fraction"] == 0.07  # override wins over preset 0.03


def test_create_run_unknown_preset_404(sim_api):
    client, _ = sim_api
    response = client.post("/api/simulation/runs", json={"preset_id": "nope"})
    assert response.status_code == 404


class _FakeMarket:
    def __init__(self, market_id):
        self.market_id = market_id


class _FakeDiscovery:
    def __init__(self, ids):
        self._ids = ids

    async def get_markets(self, limit=0):
        return [_FakeMarket(mid) for mid in self._ids[:limit]]


class _FakeFeatureEngine:
    def __init__(self, ready_ids):
        self._ready = set(ready_ids)

    def get_features(self, market_id):
        return object() if market_id in self._ready else None


def test_presets_resolve_placeholder_universe_to_real_markets(sim_api, monkeypatch):
    client, _ = sim_api
    monkeypatch.setattr(api, "market_discovery", _FakeDiscovery(["mkt-a", "mkt-b", "mkt-c", "mkt-d"]))
    monkeypatch.setattr(api, "feature_engine", _FakeFeatureEngine(["mkt-a", "mkt-b", "mkt-c", "mkt-d"]))

    presets = client.get("/api/simulation/presets").json()["presets"]
    by_id = {p["id"]: p for p in presets}

    single = by_id["single_instrument_deep"]
    assert single["suggested_universe"] == ["mkt-a"]
    assert single["universe_source"] == "live_market_discovery"

    # Non-placeholder pair legs are left untouched.
    pair = by_id["pair_arbitrage_focus"]
    assert pair["suggested_universe"] == ["binance:BTCUSDT", "hyperliquid:BTC"]
    assert pair["universe_source"] == "placeholder"

    # No placeholder ids survive in any resolved universe.
    for p in presets:
        assert not any(str(u).startswith("MARKET_ID_") for u in p["suggested_universe"])


def test_create_preset_run_uses_resolved_real_universe(sim_api, monkeypatch):
    client, _ = sim_api
    monkeypatch.setattr(api, "market_discovery", _FakeDiscovery(["mkt-x", "mkt-y"]))
    monkeypatch.setattr(api, "feature_engine", _FakeFeatureEngine(["mkt-x", "mkt-y"]))

    response = client.post(
        "/api/simulation/runs",
        json={"preset_id": "single_instrument_deep", "initial_capital": 8_000.0},
    )
    assert response.status_code == 200
    run = response.json()["run"]
    assert run["universe"] == ["mkt-x"]  # real id, not MARKET_ID_1
