"""Finnhub market-news knowledge source.

Polls Finnhub's ``/news`` endpoint across configured categories (general,
crypto, forex, …) and turns each story into a :class:`KnowledgeDocument` of
``document_type="news"``. Every item is annotated in-place with a cross-asset
impact read (see :mod:`libs.knowledge.impact`) stored in ``metadata`` and
surfaced as ``tags`` so the market-news terminal can filter by asset class
without re-analysing.

The source is dependency-light and fail-soft: a missing API key disables it,
and per-category fetch errors degrade the run rather than aborting it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

import httpx

from libs.knowledge.impact import ClaudeImpactEnhancer, analyze_impact
from libs.knowledge.models import KnowledgeDocument, utc_now
from libs.knowledge.sources.base import DiscoveredUrl, SourceRefreshResult
from libs.quant.data_quality import FreshnessPolicy, Verdict, validate_record
from libs.data.http_client import build_bounded_async_client

FINNHUB_NEWS_URL = "https://finnhub.io/api/v1/news"

# Data-quality gate policy (P8a). "Validate at ingestion — the cheapest place
# to catch issues" and enforce the schema/completeness/freshness trio before a
# record can drive a downstream conclusion. For a news feed the failure policy
# is deliberately asymmetric: a *malformed* record (missing headline / wrong
# type) is BLOCKED and dropped, whereas a *stale* one is only DOWNGRADED and
# surfaced with a marker — dropping content solely for age would silently lose
# legitimate stories, so age is made "loud" instead of invisible.
DEFAULT_FRESHNESS = FreshnessPolicy(
    warn_after=timedelta(hours=48),
    block_after=timedelta(days=30),
)


def _parse_related(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _epoch_to_dt(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


@dataclass
class FinnhubNewsSource:
    api_key: str
    categories: tuple[str, ...] = ("general", "crypto", "forex")
    max_items_per_category: int = 60
    client: httpx.AsyncClient | None = None
    enhancer: ClaudeImpactEnhancer | None = None
    now: Callable[[], datetime] = utc_now
    source_id: str = "finnhub_news"
    freshness: FreshnessPolicy = DEFAULT_FRESHNESS

    def _assess_quality(
        self, headline: str, published_at: datetime | None, now: datetime
    ) -> tuple[str, dict[str, Any]]:
        """Ingestion-time data-quality verdict for one raw news item.

        Returns ``("ok"|"degraded"|"blocked", report_dict)``. A malformed record
        (missing headline / wrong type) is ``blocked``; a stale or
        missing-timestamp record is ``degraded`` (surfaced, not dropped).
        """
        record: dict[str, Any] = {
            "headline": headline or None,
            "published_at": published_at,
        }
        report = validate_record(
            record,
            now=now,
            source_time_field="published_at",
            freshness=self.freshness,
            required_fields=("headline",),
            schema={"headline": str},
        )
        hard_block = any(
            check.verdict is Verdict.BLOCKED and check.name in ("completeness", "schema")
            for check in report.checks
        )
        stale = any(
            check.verdict is not Verdict.OK and check.name == "freshness"
            for check in report.checks
        )
        if hard_block:
            return "blocked", report.to_dict()
        if stale or report.verdict is Verdict.DEGRADED:
            return "degraded", report.to_dict()
        return "ok", report.to_dict()

    async def discover(self) -> list[DiscoveredUrl]:
        # Finnhub returns full stories directly, so there is no separate
        # discovery phase; refresh() fetches everything.
        return []

    async def refresh(self) -> SourceRefreshResult:
        if not self.api_key:
            return SourceRefreshResult(
                source_id=self.source_id,
                status="disabled",
                documents=[],
                discovered_count=0,
                fetched_count=0,
                failed_count=0,
                message="FINNHUB_API_KEY is not configured.",
            )

        client = self._client()
        documents: list[KnowledgeDocument] = []
        seen_ids: set[str] = set()
        failed_count = 0
        discovered_count = 0
        quality_stats = {"blocked": 0, "degraded": 0}

        for category in self.categories:
            try:
                response = await client.get(
                    FINNHUB_NEWS_URL,
                    params={"category": category, "token": self.api_key},
                    timeout=httpx.Timeout(15.0, connect=5.0),
                )
                response.raise_for_status()
                items = response.json()
            except Exception:
                failed_count += 1
                continue

            if not isinstance(items, list):
                failed_count += 1
                continue

            discovered_count += len(items)
            for raw in items[: self.max_items_per_category]:
                if not isinstance(raw, dict):
                    continue
                document = await self._build_document(category, raw, quality_stats)
                if document is None or document.document_id in seen_ids:
                    continue
                seen_ids.add(document.document_id)
                documents.append(document)

        quality_note = ""
        if quality_stats["blocked"] or quality_stats["degraded"]:
            quality_note = (
                f" (data-quality: {quality_stats['blocked']} blocked, "
                f"{quality_stats['degraded']} degraded)"
            )

        if not documents and failed_count:
            status = "error"
            message = f"all {failed_count} category fetches failed"
        elif failed_count:
            status = "degraded"
            message = f"{failed_count} category fetches failed{quality_note}"
        elif quality_stats["blocked"]:
            status = "degraded"
            message = f"ok{quality_note}"
        else:
            status = "ok"
            message = f"ok{quality_note}" if quality_note else "ok"

        return SourceRefreshResult(
            source_id=self.source_id,
            status=status,
            documents=documents,
            discovered_count=discovered_count,
            fetched_count=len(documents),
            failed_count=failed_count,
            message=message,
        )

    async def _build_document(
        self,
        category: str,
        raw: dict[str, Any],
        quality_stats: dict[str, int] | None = None,
    ) -> KnowledgeDocument | None:
        stats = quality_stats if quality_stats is not None else {"blocked": 0, "degraded": 0}
        headline = str(raw.get("headline") or "").strip()
        published_at = _epoch_to_dt(raw.get("datetime"))

        # Data-quality gate (P8a): refuse malformed records outright, mark stale
        # ones. Runs before the (potentially expensive) impact analysis so bad
        # data never consumes downstream work.
        verdict, quality_report = self._assess_quality(headline, published_at, self.now())
        if verdict == "blocked":
            stats["blocked"] = stats.get("blocked", 0) + 1
            return None
        if verdict == "degraded":
            stats["degraded"] = stats.get("degraded", 0) + 1

        summary = str(raw.get("summary") or "").strip()
        related = _parse_related(raw.get("related"))
        news_id = raw.get("id")
        document_id = f"finnhub:{news_id}" if news_id else f"finnhub:{abs(hash(headline))}"

        analysis = analyze_impact(
            headline,
            summary=summary,
            category=category,
            related=related,
        )
        if self.enhancer is not None and self.enhancer.available:
            analysis = await self.enhancer.enhance(headline, summary, analysis)

        tags = list(dict.fromkeys([f"category:{category}", *analysis.asset_tags]))
        if verdict == "degraded":
            tags.append("quality:degraded")

        return KnowledgeDocument(
            source_id=self.source_id,
            document_id=document_id,
            url=str(raw.get("url") or ""),
            title=headline,
            document_type="news",
            ticker=(related[0] if related else None),
            company_name=None,
            published_at=published_at,
            updated_at=published_at,
            captured_at=self.now().astimezone(UTC),
            language="en",
            summary=summary or headline,
            content=summary or headline,
            tags=tags,
            metadata={
                "provider": "finnhub",
                "category": category,
                "news_source": str(raw.get("source") or ""),
                "related": related,
                "image": str(raw.get("image") or ""),
                "data_quality": quality_report,
                **analysis.to_metadata(),
            },
        )

    def _client(self) -> httpx.AsyncClient:
        if self.client is not None:
            return self.client
        self.client = build_bounded_async_client(
            headers={"User-Agent": "PolyBobMarketNews/0.1"},
            follow_redirects=True,
        )
        return self.client


__all__ = ["FinnhubNewsSource"]
