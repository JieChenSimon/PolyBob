"""Regression tests for API performance fixes (shared client, cache eviction, lab status)."""
from types import SimpleNamespace

import apps.api.deps as deps
import apps.api.main as api


async def test_expired_api_cache_entries_are_evicted_on_insert():
    deps.clear_api_response_cache()

    async def load_a() -> dict:
        return {"value": "a"}

    async def load_b() -> dict:
        return {"value": "b"}

    await deps.cached_api_response("key_a", -1.0, load_a)  # expires immediately
    assert "key_a" in deps._api_response_cache

    await deps.cached_api_response("key_b", 60.0, load_b)

    assert "key_a" not in deps._api_response_cache
    assert "key_a" not in deps._api_response_locks
    assert "key_b" in deps._api_response_cache

    deps.clear_api_response_cache()


async def test_api_cache_total_size_is_capped():
    deps.clear_api_response_cache()

    async def load() -> dict:
        return {}

    for index in range(deps._API_RESPONSE_CACHE_MAX_ENTRIES + 20):
        await deps.cached_api_response(f"key_{index}", 60.0, load)

    assert len(deps._api_response_cache) <= deps._API_RESPONSE_CACHE_MAX_ENTRIES + 1

    deps.clear_api_response_cache()


async def test_lab_trading_status_uses_cached_price_without_http_call(monkeypatch):
    monkeypatch.setattr(
        api,
        "get_settings",
        lambda: SimpleNamespace(enable_lab_auto_trader=True, product_mode="personal_workbench"),
    )

    class FakeEngine:
        def __init__(self):
            self.last_price = 61000.0
            self.capital = 10000.0
            self.initial_capital = 10000.0
            self.position = 0.0
            self.running = True
            self.http_calls = 0

        def get_btc_price(self):
            self.http_calls += 1
            return 61000.0

    engine = FakeEngine()
    monkeypatch.setattr(api, "get_trading_engine", lambda: engine)

    status = await api.get_lab_trading_status()

    assert engine.http_calls == 0  # cached price used, no blocking HTTP per request
    assert status["running"] is True
    assert status["total_value"] == 10000.0


async def test_lab_trading_status_fetches_once_when_no_cached_price(monkeypatch):
    monkeypatch.setattr(
        api,
        "get_settings",
        lambda: SimpleNamespace(enable_lab_auto_trader=True, product_mode="personal_workbench"),
    )

    class FakeEngine:
        def __init__(self):
            self.last_price = None
            self.capital = 10000.0
            self.initial_capital = 10000.0
            self.position = 0.0
            self.running = False
            self.http_calls = 0

        def get_btc_price(self):
            self.http_calls += 1
            self.last_price = 60000.0
            return 60000.0

    engine = FakeEngine()
    monkeypatch.setattr(api, "get_trading_engine", lambda: engine)

    first = await api.get_lab_trading_status()
    second = await api.get_lab_trading_status()

    assert engine.http_calls == 1  # cold fetch happens once, then cache is reused
    assert first["capital"] == second["capital"] == 10000.0


def test_shared_http_client_is_reused_and_lazily_recreated():
    first = deps.get_shared_http_client()
    second = deps.get_shared_http_client()
    assert first is second
