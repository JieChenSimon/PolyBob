from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
import httpx

import apps.api.main as api


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = payload if isinstance(payload, str) else json.dumps(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    def __init__(self):
        self.urls = []

    async def get(self, url, params=None):
        self.urls.append((url, params))
        if url.endswith("/markets"):
            return FakeResponse([])
        return FakeResponse({
            "eventMetadata": {"priceToBeat": 61189.13539580122},
            "markets": [
                {
                    "id": "2665625",
                    "conditionId": "0xabc",
                    "slug": "btc-updown-5m-1782384600",
                    "question": "Bitcoin Up or Down",
                    "outcomes": '["Up", "Down"]',
                    "clobTokenIds": '["up-token", "down-token"]',
                    "active": True,
                    "closed": False,
                    "enableOrderBook": True,
                }
            ]
        })


async def fake_unavailable_btc_reference():
    return {
        "source": "okx_swap",
        "symbol": "BTC-USDT-SWAP",
        "price": 59000.0,
        "timestamp": "2026-06-26T03:00:00Z",
        "received_at": "2026-06-26T03:00:00Z",
        "round_trip_ms": 100,
        "staleness_ms": 10,
        "latency_quality": "provider_timestamp",
        "sources": [{"source": "okx_swap", "status": "ok", "selected": True, "price": 59000.0}],
    }


@pytest.mark.asyncio
async def test_gamma_market_fetch_uses_event_slug_for_target_price_metadata():
    client = FakeClient()

    market = await api.fetch_btc_five_minute_gamma_market(
        client,
        gamma_base_url="https://gamma-api.polymarket.com",
        slug="btc-updown-5m-1782384600",
    )

    assert market["conditionId"] == "0xabc"
    assert client.urls[0][0].endswith("/events/slug/btc-updown-5m-1782384600")
    assert market["eventMetadata"]["priceToBeat"] == 61189.13539580122


def test_extracts_live_target_price_from_polymarket_page_crypto_prices():
    html = (
        '"state":{"data":{"openPrice":61187.70127318885,"closePrice":null},'
        '"dataUpdateCount":1},'
        '"queryKey":["crypto-prices","price","BTC","2026-06-25T12:00:00Z",'
        '"fiveminute","2026-06-25T12:05:00Z"]'
    )

    price = api._extract_btc_five_minute_page_target_price(
        html,
        "2026-06-25T12:00:00Z",
        "2026-06-25T12:05:00Z",
    )

    assert price == 61187.70127318885


def test_extracts_target_price_from_backslash_escaped_page_state():
    # Polymarket dehydrates its React Query cache as a JSON *string*, so quotes
    # arrive backslash-escaped. The parser must survive that encoding.
    html = (
        r'...\"state\":{\"data\":{\"openPrice\":66803.45651435753,\"closePrice\":null},'
        r'\"dataUpdateCount\":1,\"status\":\"success\"},'
        r'\"queryKey\":[\"crypto-prices\",\"price\",\"BTC\",\"2026-07-21T15:00:00Z\",'
        r'\"fiveminute\",\"2026-07-21T15:05:00Z\"],\"queryHash\":...'
    )

    price = api._extract_btc_five_minute_page_target_price(
        html,
        "2026-07-21T15:00:00Z",
        "2026-07-21T15:05:00Z",
    )

    assert price == 66803.45651435753


@pytest.mark.asyncio
async def test_fetches_target_price_from_crypto_price_api():
    class ApiClient:
        def __init__(self):
            self.calls = []

        async def get(self, url, params=None, headers=None):
            self.calls.append((url, params))
            assert url == "https://polymarket.com/api/crypto/crypto-price"
            assert params == {
                "symbol": "BTC",
                "eventStartTime": "2026-06-25T12:00:00Z",
                "variant": "fiveminute",
                "endDate": "2026-06-25T12:05:00Z",
            }
            return FakeResponse(
                {
                    "openPrice": 66752.3743301865,
                    "closePrice": None,
                    "timestamp": 1784646630258,
                    "incomplete": True,
                }
            )

    target = await api.fetch_btc_five_minute_api_target_price(
        ApiClient(),
        slug="btc-updown-5m-1782388800",
    )

    assert target == {
        "source": "polymarket_crypto_price_api",
        "price": 66752.3743301865,
        "field": "crypto-price.openPrice",
    }


@pytest.mark.asyncio
async def test_target_price_api_missing_open_price_raises():
    class ApiClient:
        async def get(self, url, params=None, headers=None):
            return FakeResponse({"openPrice": None, "closePrice": None})

    with pytest.raises(ValueError):
        await api.fetch_btc_five_minute_api_target_price(
            ApiClient(),
            slug="btc-updown-5m-1782388800",
        )


@pytest.mark.asyncio
async def test_fetches_live_target_price_from_polymarket_page():
    class PageClient:
        async def get(self, url, headers=None):
            assert url == "https://polymarket.com/event/btc-updown-5m-1782388800"
            assert headers and "User-Agent" in headers
            return FakeResponse(
                '"state":{"data":{"openPrice":61187.70127318885,"closePrice":null},'
                '"dataUpdateCount":1},'
                '"queryKey":["crypto-prices","price","BTC","2026-06-25T12:00:00Z",'
                '"fiveminute","2026-06-25T12:05:00Z"]'
            )

    target = await api.fetch_btc_five_minute_page_target_price(
        PageClient(),
        slug="btc-updown-5m-1782388800",
    )

    assert target == {
        "source": "polymarket_page_crypto_prices",
        "price": 61187.70127318885,
        "field": "crypto-prices.openPrice",
    }


@pytest.mark.asyncio
async def test_btc_reference_aggregator_selects_lowest_staleness_timestamped_source():
    class MultiSourceClient:
        async def get(self, url, params=None, headers=None):
            if "binance.com" in url:
                return FakeResponse({"symbol": "BTCUSDT", "price": "61200.10", "time": 1782388800100})
            if "okx.com" in url:
                return FakeResponse({"data": [{"instId": "BTC-USDT-SWAP", "last": "61201.20", "ts": "1782388800300"}]})
            if "coinbase.com" in url:
                return FakeResponse({"price": "61250.00", "time": "2026-06-25T12:00:00.000Z"})
            raise AssertionError(f"unexpected url {url}")

    now = datetime.fromtimestamp(1782388800.500, tz=timezone.utc)

    reference = await api.fetch_btc_reference_aggregate(MultiSourceClient(), now=now)

    assert reference["source"] == "okx_swap"
    assert reference["price"] == 61201.20
    assert reference["latency_quality"] == "provider_timestamp"
    assert len(reference["sources"]) == 3
    okx = next(source for source in reference["sources"] if source["source"] == "okx_swap")
    assert okx["selected"] is True
    assert okx["staleness_ms"] == 200
    assert okx["round_trip_ms"] >= 0


@pytest.mark.asyncio
async def test_btc_reference_aggregator_keeps_failed_sources_and_rejects_outliers():
    class PartialClient:
        async def get(self, url, params=None, headers=None):
            if "binance.com" in url:
                return FakeResponse({"symbol": "BTCUSDT", "price": "61200.10", "time": 1782388800100})
            if "okx.com" in url:
                return FakeResponse({"data": [{"instId": "BTC-USDT-SWAP", "last": "64000.00", "ts": "1782388800300"}]})
            if "coinbase.com" in url:
                raise httpx.ConnectTimeout("coinbase timeout", request=httpx.Request("GET", url))
            raise AssertionError(f"unexpected url {url}")

    now = datetime.fromtimestamp(1782388800.500, tz=timezone.utc)

    reference = await api.fetch_btc_reference_aggregate(PartialClient(), now=now)

    assert reference["source"] == "binance_futures"
    assert reference["price"] == 61200.10
    assert any(source["source"] == "coinbase_spot" and source["status"] == "error" for source in reference["sources"])
    okx = next(source for source in reference["sources"] if source["source"] == "okx_swap")
    assert okx["status"] == "outlier"
    assert okx["selected"] is False


@pytest.mark.asyncio
async def test_btc_five_minute_endpoint_returns_workbench_payload(monkeypatch):
    api.clear_api_response_cache()

    async def fake_collect(slug=None):
        return {
            "source": "polymarket_clob",
            "action": "watch_up",
            "recommended_outcome": "UP",
            "reason_codes": [],
            "slug": "btc-updown-5m-1782384600",
            "now": datetime.fromtimestamp(1782384701, tz=timezone.utc).isoformat(),
            "entry_optimizer": {
                "decision": "enter",
                "recommended_outcome": "UP",
                "core_conclusion": "当前入场候选：UP，限价不高于 0.500，建议仓位 3.00%。",
            },
            "outcomes": {
                "UP": {
                    "token_id": "up-token",
                    "is_real_orderbook": True,
                    "candidate_entry_price": 0.5,
                    "entry_analysis": {
                        "entry_decision": "enter",
                        "max_acceptable_price": 0.5,
                        "win_probability": 0.62,
                        "expected_value": 0.08,
                        "kelly_fraction": 0.03,
                    },
                },
                "DOWN": {
                    "token_id": "down-token",
                    "is_real_orderbook": True,
                    "candidate_entry_price": None,
                    "entry_analysis": {
                        "entry_decision": "avoid",
                        "max_acceptable_price": 0.3,
                        "win_probability": 0.38,
                        "expected_value": -0.08,
                        "kelly_fraction": 0.0,
                    },
                },
            },
        }

    monkeypatch.setattr(api, "collect_btc_five_minute_workbench", fake_collect)

    payload = await api.get_btc_five_minute_workbench()

    assert payload["source"] == "polymarket_clob"
    assert payload["action"] == "watch_up"
    assert payload["entry_optimizer"]["decision"] == "enter"
    assert payload["entry_optimizer"]["recommended_outcome"] == "UP"
    assert payload["outcomes"]["UP"]["is_real_orderbook"] is True
    assert payload["outcomes"]["UP"]["entry_analysis"]["entry_decision"] == "enter"


@pytest.mark.asyncio
async def test_btc_five_minute_endpoint_cache_is_window_aware(monkeypatch):
    api.clear_api_response_cache()
    calls = 0

    async def fake_collect(slug=None):
        nonlocal calls
        calls += 1
        return {
            "source": "polymarket_clob",
            "action": "no_trade",
            "recommended_outcome": None,
            "reason_codes": [],
            "slug": slug,
            "outcomes": {},
        }

    monkeypatch.setattr(api, "collect_btc_five_minute_workbench", fake_collect)

    first = await api.get_btc_five_minute_workbench(slug="btc-updown-5m-1782384600")
    second = await api.get_btc_five_minute_workbench(slug="btc-updown-5m-1782384900")

    assert first["slug"] == "btc-updown-5m-1782384600"
    assert second["slug"] == "btc-updown-5m-1782384900"
    assert calls == 2


@pytest.mark.asyncio
async def test_btc_five_minute_endpoint_fails_closed_without_fake_book(monkeypatch):
    api.clear_api_response_cache()

    async def fake_collect(slug=None):
        raise RuntimeError("Gamma market unavailable")

    monkeypatch.setattr(api, "collect_btc_five_minute_workbench", fake_collect)
    monkeypatch.setattr(api, "fetch_btc_reference_for_unavailable_workbench", fake_unavailable_btc_reference)

    payload = await api.get_btc_five_minute_workbench()

    assert payload["source"] == "unavailable"
    assert payload["action"] == "no_trade"
    assert payload["btc_reference"]["source"] == "okx_swap"
    assert payload["btc_reference"]["price"] == 59000.0
    assert payload["data_health"]["btc_reference"]["status"] == "ok"
    assert payload["data_health"]["polymarket_market"]["status"] == "unavailable"
    assert payload["data_health"]["polymarket_orderbook"]["status"] == "unavailable"
    assert "Gamma market unavailable" in payload["data_health"]["polymarket_market"]["message"]
    assert payload["reason_codes"] == ["WORKBENCH_UNAVAILABLE"]
    assert "Gamma market unavailable" in payload["error"]
    assert payload["error_diagnosis"]["category"] == "unknown"
    assert payload["error_diagnosis"]["retryable"] is True


@pytest.mark.asyncio
async def test_btc_five_minute_endpoint_reports_exception_class_when_message_empty(monkeypatch):
    api.clear_api_response_cache()

    async def fake_collect(slug=None):
        raise TimeoutError()

    monkeypatch.setattr(api, "collect_btc_five_minute_workbench", fake_collect)
    monkeypatch.setattr(api, "fetch_btc_reference_for_unavailable_workbench", fake_unavailable_btc_reference)

    payload = await api.get_btc_five_minute_workbench()

    assert payload["source"] == "unavailable"
    assert payload["action"] == "no_trade"
    assert payload["error"] == "TimeoutError"
    assert payload["error_diagnosis"]["category"] == "network_timeout"


@pytest.mark.asyncio
async def test_gamma_market_fetch_does_not_retry_transport_failures():
    class TimeoutClient:
        def __init__(self):
            self.calls = 0

        async def get(self, url, params=None):
            self.calls += 1
            if url.endswith("/events/slug/btc-updown-5m-1782384600"):
                raise httpx.ConnectTimeout("Gamma event timeout")
            if url.endswith("/markets"):
                return FakeResponse([
                    {
                        "id": "2665625",
                        "conditionId": "0xabc",
                        "slug": "btc-updown-5m-1782384600",
                        "question": "Bitcoin Up or Down",
                        "outcomes": '["Up", "Down"]',
                        "clobTokenIds": '["up-token", "down-token"]',
                        "active": True,
                        "closed": False,
                        "enableOrderBook": True,
                    }
                ])
            raise AssertionError(f"unexpected url {url}")

    client = TimeoutClient()

    market = await api.fetch_btc_five_minute_gamma_market(
        client,
        gamma_base_url="https://gamma-api.polymarket.com",
        slug="btc-updown-5m-1782384600",
    )

    assert market["conditionId"] == "0xabc"
    assert client.calls == 2


@pytest.mark.asyncio
async def test_gamma_market_fetch_uses_markets_fallback_after_event_503():
    class ServiceUnavailableClient:
        def __init__(self):
            self.calls = 0

        async def get(self, url, params=None):
            self.calls += 1
            if "/events/slug/" in url:
                return FakeResponse({"error": "unavailable"}, status_code=503)
            return FakeResponse([
                {
                    "id": "2665625",
                    "conditionId": "0xabc",
                    "slug": "btc-updown-5m-1782384600",
                    "question": "Bitcoin Up or Down",
                    "outcomes": '["Up", "Down"]',
                    "clobTokenIds": '["up-token", "down-token"]',
                    "active": True,
                    "closed": False,
                    "enableOrderBook": True,
                }
            ])

    client = ServiceUnavailableClient()

    market = await api.fetch_btc_five_minute_gamma_market(
        client,
        gamma_base_url="https://gamma-api.polymarket.com",
        slug="btc-updown-5m-1782384600",
    )

    assert market["conditionId"] == "0xabc"
    assert client.calls == 2


@pytest.mark.asyncio
async def test_btc_reference_safe_uses_short_cache(monkeypatch):
    api.clear_api_response_cache()
    calls = 0

    async def fake_aggregate(client):
        nonlocal calls
        calls += 1
        return {
            "source": "okx_swap",
            "symbol": "BTC-USDT-SWAP",
            "price": 59000 + calls,
            "timestamp": "2026-06-26T02:08:50Z",
            "received_at": "2026-06-26T02:08:50Z",
            "staleness_ms": 5,
            "round_trip_ms": 100,
            "latency_quality": "provider_timestamp",
            "sources": [],
        }

    monkeypatch.setattr(api, "fetch_btc_reference_aggregate", fake_aggregate)

    first = await api._fetch_btc_reference_aggregate_safe(object())
    second = await api._fetch_btc_reference_aggregate_safe(object())

    assert first["price"] == second["price"]
    assert calls == 1


@pytest.mark.asyncio
async def test_realtime_market_uses_multi_source_reference(monkeypatch):
    async def fake_reference(client):
        return {
            "source": "coinbase_spot",
            "symbol": "BTC-USD",
            "price": 59314.72,
            "timestamp": "2026-06-26T02:08:50Z",
            "received_at": "2026-06-26T02:08:50Z",
            "staleness_ms": 5,
            "round_trip_ms": 806,
            "latency_quality": "provider_timestamp",
            "sources": [{"source": "coinbase_spot", "status": "ok", "selected": True}],
        }

    monkeypatch.setattr(api, "_fetch_btc_reference_aggregate_safe", fake_reference)

    payload = await api.get_realtime_market()

    assert payload["source"] == "coinbase_spot"
    assert payload["price"] == 59314.72
    assert payload["sources"][0]["selected"] is True


@pytest.mark.asyncio
async def test_btc_five_minute_endpoint_diagnoses_provider_503(monkeypatch):
    api.clear_api_response_cache()
    request = httpx.Request("GET", "https://gamma-api.polymarket.com/markets")
    response = httpx.Response(503, request=request, text="Service Unavailable")

    async def fake_collect(slug=None):
        raise httpx.HTTPStatusError(
            "503 Service Unavailable",
            request=request,
            response=response,
        )

    monkeypatch.setattr(api, "collect_btc_five_minute_workbench", fake_collect)
    monkeypatch.setattr(api, "fetch_btc_reference_for_unavailable_workbench", fake_unavailable_btc_reference)

    payload = await api.get_btc_five_minute_workbench()

    assert payload["source"] == "unavailable"
    assert payload["error_diagnosis"]["category"] == "provider_status"
    assert payload["error_diagnosis"]["responsibility"] == "external_provider"
    assert payload["error_diagnosis"]["provider"] == "Polymarket Gamma"
    assert "Polymarket" in payload["error_diagnosis"]["likely_cause"]


@pytest.mark.asyncio
async def test_btc_five_minute_endpoint_diagnoses_network_connection(monkeypatch):
    api.clear_api_response_cache()
    request = httpx.Request("GET", "https://clob.polymarket.com/book")

    async def fake_collect(slug=None):
        raise httpx.ConnectError("SSL handshake failed", request=request)

    monkeypatch.setattr(api, "collect_btc_five_minute_workbench", fake_collect)
    monkeypatch.setattr(api, "fetch_btc_reference_for_unavailable_workbench", fake_unavailable_btc_reference)

    payload = await api.get_btc_five_minute_workbench()

    assert payload["error_diagnosis"]["category"] == "network_connection"
    assert payload["error_diagnosis"]["provider"] == "Polymarket CLOB"
    assert "网络" in payload["error_diagnosis"]["user_action"]


@pytest.mark.asyncio
async def test_btc_five_minute_endpoint_diagnoses_503_inside_transport_error(monkeypatch):
    api.clear_api_response_cache()
    request = httpx.Request("GET", "https://gamma-api.polymarket.com/markets")

    async def fake_collect(slug=None):
        raise httpx.ConnectError("503 Service Unavailable", request=request)

    monkeypatch.setattr(api, "collect_btc_five_minute_workbench", fake_collect)
    monkeypatch.setattr(api, "fetch_btc_reference_for_unavailable_workbench", fake_unavailable_btc_reference)

    payload = await api.get_btc_five_minute_workbench()

    assert payload["error_diagnosis"]["category"] == "provider_status"
    assert payload["error_diagnosis"]["responsibility"] == "external_provider"
    assert payload["error_diagnosis"]["provider"] == "Polymarket Gamma"
