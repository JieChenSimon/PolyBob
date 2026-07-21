"""API contract tests for the market-news terminal endpoint."""

from __future__ import annotations

import pytest

import apps.api.main as api
from libs.knowledge.store import KnowledgeStore
from libs.knowledge.sources.finnhub_news import FinnhubNewsSource


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class _FakeClient:
    def __init__(self, by_category):
        self.by_category = by_category

    async def get(self, url, params=None, timeout=None):
        return _FakeResponse(self.by_category.get(params["category"], []))


class _NewsService:
    def __init__(self, store: KnowledgeStore) -> None:
        self.store = store

    def search(self, **kwargs):
        return self.store.search(**kwargs)


@pytest.fixture
def market_news_api(monkeypatch, tmp_path):
    store = KnowledgeStore(tmp_path / "news.sqlite3")
    store.init()
    monkeypatch.setattr(api, "market_news_service", _NewsService(store))
    api.clear_api_response_cache()
    return store


async def _seed_news(store: KnowledgeStore):
    source = FinnhubNewsSource(
        api_key="test",
        categories=("crypto", "general"),
        client=_FakeClient(
            {
                "crypto": [
                    {
                        "id": 1,
                        "headline": "Bitcoin surges to record high on ETF inflows",
                        "summary": "BTC rallies.",
                        "url": "https://example.com/a",
                        "source": "CoinDesk",
                        "datetime": 1_784_600_000,
                        "related": "BTC",
                    }
                ],
                "general": [
                    {
                        "id": 2,
                        "headline": "Stocks plunge on recession fears and geopolitical crisis",
                        "summary": "Equities selloff.",
                        "url": "https://example.com/b",
                        "source": "Reuters",
                        "datetime": 1_784_600_500,
                        "related": "",
                    }
                ],
            }
        ),
    )
    result = await source.refresh()
    for doc in result.documents:
        store.upsert_document(doc)


@pytest.mark.asyncio
async def test_market_news_feed_returns_impacts(market_news_api):
    await _seed_news(market_news_api)

    payload = await api.get_market_news(limit=10)

    assert payload["count"] == 2
    assert "crypto" in payload["asset_classes"]
    headlines = {item["headline"] for item in payload["items"]}
    assert any("Bitcoin surges" in h for h in headlines)
    btc = next(item for item in payload["items"] if "Bitcoin" in item["headline"])
    assert btc["sentiment"] == "bullish"
    assert any(i["asset_class"] == "crypto" for i in btc["impacts"])


@pytest.mark.asyncio
async def test_market_news_filters_by_asset_class(market_news_api):
    await _seed_news(market_news_api)

    payload = await api.get_market_news(asset_class="gold", limit=10)

    # Only the risk-off equities story spills over to gold (safe haven).
    assert payload["filter"] == "gold"
    assert payload["count"] == 1
    item = payload["items"][0]
    assert "plunge" in item["headline"].lower()
    gold = next(i for i in item["impacts"] if i["asset_class"] == "gold")
    assert gold["direction"] == "bullish"


@pytest.mark.asyncio
async def test_market_news_rejects_unknown_asset_class(market_news_api):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await api.get_market_news(asset_class="tulips")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_market_news_requires_service(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(api, "market_news_service", None)
    with pytest.raises(HTTPException) as exc:
        await api.get_market_news()
    assert exc.value.status_code == 503
