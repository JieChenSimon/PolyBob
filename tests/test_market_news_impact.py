"""Tests for cross-asset news impact analysis and the Finnhub news source."""

from __future__ import annotations

import pytest

from libs.knowledge.impact import ASSET_CLASSES, analyze_impact
from libs.knowledge.sources.finnhub_news import FinnhubNewsSource


def _impact_for(analysis, asset_class):
    return next((i for i in analysis.impacts if i.asset_class == asset_class), None)


def test_crypto_rally_is_bullish_for_crypto():
    analysis = analyze_impact(
        "Bitcoin surges to record high as spot ETF inflows jump",
        summary="BTC rallies amid strong demand.",
        category="crypto",
    )
    crypto = _impact_for(analysis, "crypto")
    assert crypto is not None
    assert crypto.direction == "bullish"
    assert analysis.sentiment == "bullish"
    assert "crypto" in analysis.asset_tags


def test_hawkish_fed_pressures_risk_and_supports_dollar():
    analysis = analyze_impact(
        "Fed signals rate hike as hot inflation data lifts Treasury yields",
        summary="Hawkish tone from Powell.",
        category="general",
    )
    equities = _impact_for(analysis, "us_equities")
    fx = _impact_for(analysis, "fx")
    rates = _impact_for(analysis, "rates")
    assert rates is not None
    # Hawkish policy: risk assets down, dollar up.
    if equities is not None:
        assert equities.direction == "bearish"
    assert fx is not None and fx.direction == "bullish"


def test_risk_off_headline_gives_gold_safe_haven_bid():
    analysis = analyze_impact(
        "Global stocks plunge on recession fears and geopolitical selloff",
        summary="Investors flee to safety as equities crash.",
        category="general",
    )
    assert analysis.sentiment == "bearish"
    gold = _impact_for(analysis, "gold")
    equities = _impact_for(analysis, "us_equities")
    assert equities is not None and equities.direction == "bearish"
    assert gold is not None and gold.direction == "bullish"
    assert "safe-haven" in gold.rationale


def test_neutral_headline_has_no_direction_bias():
    analysis = analyze_impact(
        "Company announces new headquarters location",
        summary="A routine corporate update.",
        category="general",
    )
    assert analysis.sentiment == "neutral"


def test_confidence_is_bounded():
    analysis = analyze_impact(
        "Bitcoin surges rally soar jump gain rise record high beat upgrade boost",
        category="crypto",
    )
    for impact in analysis.impacts:
        assert 0.0 <= impact.confidence <= 1.0
        assert impact.asset_class in ASSET_CLASSES


@pytest.mark.asyncio
async def test_finnhub_source_disabled_without_key():
    source = FinnhubNewsSource(api_key="")
    result = await source.refresh()
    assert result.status == "disabled"
    assert result.documents == []


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
        self.calls = []

    async def get(self, url, params=None, timeout=None):
        category = params["category"]
        self.calls.append(category)
        return _FakeResponse(self.by_category.get(category, []))


@pytest.mark.asyncio
async def test_finnhub_source_builds_annotated_news_documents():
    client = _FakeClient(
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
                    "id": 1,  # duplicate id across categories -> deduped
                    "headline": "Bitcoin surges to record high on ETF inflows",
                    "summary": "BTC rallies.",
                    "url": "https://example.com/a",
                    "source": "CoinDesk",
                    "datetime": 1_784_600_000,
                    "related": "BTC",
                },
                {
                    "id": 2,
                    "headline": "Stocks plunge on recession fears",
                    "summary": "Equities selloff.",
                    "url": "https://example.com/b",
                    "source": "Reuters",
                    "datetime": 1_784_600_500,
                    "related": "",
                },
            ],
        }
    )
    source = FinnhubNewsSource(
        api_key="test-key",
        categories=("crypto", "general"),
        client=client,
    )

    result = await source.refresh()

    assert result.status == "ok"
    # 3 raw items, one deduped by id -> 2 documents.
    assert result.fetched_count == 2
    ids = {doc.document_id for doc in result.documents}
    assert ids == {"finnhub:1", "finnhub:2"}

    btc_doc = next(doc for doc in result.documents if doc.document_id == "finnhub:1")
    assert btc_doc.document_type == "news"
    assert btc_doc.ticker == "BTC"
    assert "crypto" in btc_doc.tags
    impacts = btc_doc.metadata["impacts"]
    assert any(i["asset_class"] == "crypto" and i["direction"] == "bullish" for i in impacts)
    assert btc_doc.metadata["analysis_engine"] == "heuristic"


@pytest.mark.asyncio
async def test_finnhub_source_degrades_on_partial_failure():
    class _PartialClient:
        async def get(self, url, params=None, timeout=None):
            if params["category"] == "crypto":
                raise RuntimeError("boom")
            return _FakeResponse(
                [
                    {
                        "id": 9,
                        "headline": "Gold climbs as dollar weakens",
                        "summary": "",
                        "url": "https://example.com/g",
                        "source": "Bloomberg",
                        "datetime": 1_784_600_900,
                        "related": "",
                    }
                ]
            )

    source = FinnhubNewsSource(
        api_key="test-key",
        categories=("crypto", "forex"),
        client=_PartialClient(),
    )
    result = await source.refresh()
    assert result.status == "degraded"
    assert result.failed_count == 1
    assert result.fetched_count == 1
