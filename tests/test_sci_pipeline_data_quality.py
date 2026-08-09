"""P8a — data-quality gate at ingestion.

Proves that stale/malformed records entering the pipeline are blocked (dropped)
or downgraded (marked) rather than silently used, at two entry points:
the Finnhub news source and the feature-snapshot publish path.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from libs.knowledge.sources.finnhub_news import FinnhubNewsSource
from modules.feature_engine.service import FeatureEngineService


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, by_category):
        self.by_category = by_category

    async def get(self, url, params=None, timeout=None):
        return _FakeResponse(self.by_category.get(params["category"], []))


NOW = datetime(2026, 7, 22, tzinfo=UTC)


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


# ------------------------------------------------------------ Finnhub gate


@pytest.mark.asyncio
async def test_stale_news_item_is_downgraded_not_dropped():
    stale_dt = NOW - timedelta(days=200)  # well past the 30d block threshold
    client = _FakeClient(
        {
            "crypto": [
                {
                    "id": 1,
                    "headline": "Old news that should be marked stale",
                    "summary": "s",
                    "url": "https://example.com/old",
                    "datetime": _epoch(stale_dt),
                    "related": "BTC",
                }
            ]
        }
    )
    source = FinnhubNewsSource(
        api_key="k", categories=("crypto",), client=client, now=lambda: NOW
    )

    result = await source.refresh()

    assert result.fetched_count == 1  # surfaced, not dropped
    doc = result.documents[0]
    assert "quality:degraded" in doc.tags
    assert doc.metadata["data_quality"]["verdict"] in ("degraded", "blocked")
    # freshness check is the one that flagged it
    reasons = " ".join(c["detail"] for c in doc.metadata["data_quality"]["checks"])
    assert "old" in reasons


@pytest.mark.asyncio
async def test_malformed_news_item_is_blocked_and_dropped():
    client = _FakeClient(
        {
            "crypto": [
                {  # missing headline -> malformed -> blocked
                    "id": 1,
                    "summary": "no headline here",
                    "url": "https://example.com/bad",
                    "datetime": _epoch(NOW - timedelta(hours=1)),
                },
                {  # fresh + well-formed -> kept, verdict ok
                    "id": 2,
                    "headline": "Good fresh story",
                    "summary": "s",
                    "url": "https://example.com/ok",
                    "datetime": _epoch(NOW - timedelta(hours=1)),
                    "related": "ETH",
                },
            ]
        }
    )
    source = FinnhubNewsSource(
        api_key="k", categories=("crypto",), client=client, now=lambda: NOW
    )

    result = await source.refresh()

    ids = {doc.document_id for doc in result.documents}
    assert ids == {"finnhub:2"}  # malformed item dropped
    # a blocked item forces the run status to reflect the degradation
    assert result.status == "degraded"
    assert "blocked" in result.message
    good = result.documents[0]
    assert good.metadata["data_quality"]["verdict"] == "ok"
    assert "quality:degraded" not in good.tags


# ------------------------------------------------------ feature-snapshot gate


def _snapshot(market_id="m1", mid=0.96, spread_bps=20.0, age_seconds=0.0):
    return {
        "market_id": market_id,
        "timestamp": datetime.utcnow() - timedelta(seconds=age_seconds),
        "mid_price": mid,
        "spread_bps": spread_bps,
        "bid_price": 0.95,
        "ask_price": 0.97,
        "bid_size": 100.0,
        "ask_size": 100.0,
        "depth_imbalance": 0.0,
    }


def test_fresh_feature_snapshot_passes_clean():
    engine = FeatureEngineService()
    out = engine._gate_snapshot(_snapshot(age_seconds=1.0))
    assert out is not None
    assert "data_quality" not in out  # ok -> unannotated


def test_stale_feature_snapshot_is_marked_degraded():
    engine = FeatureEngineService()
    out = engine._gate_snapshot(_snapshot(age_seconds=60.0))  # > 30s warn, < 300s block
    assert out is not None
    assert out["data_quality"]["verdict"] == "degraded"


def test_very_stale_feature_snapshot_is_blocked():
    engine = FeatureEngineService()
    out = engine._gate_snapshot(_snapshot(age_seconds=600.0))  # > 300s block
    assert out is None


def test_malformed_feature_snapshot_is_blocked():
    engine = FeatureEngineService()
    snap = _snapshot(age_seconds=1.0)
    del snap["mid_price"]  # required field missing
    assert engine._gate_snapshot(snap) is None
