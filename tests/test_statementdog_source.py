import gzip
from datetime import UTC, datetime

import httpx
import pytest

from libs.knowledge.sources.statementdog import StatementDogSource, parse_statementdog_html


SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://statementdog.com/analysis/TER</loc>
    <lastmod>2026-04-16T09:55:28+08:00</lastmod>
  </url>
  <url>
    <loc>https://statementdog.com/blog/archives/14687</loc>
    <lastmod>2026-05-20T22:33:35+08:00</lastmod>
  </url>
  <url>
    <loc>https://statementdog.com/tags/1517</loc>
    <lastmod>2026-07-03T05:00:43+08:00</lastmod>
  </url>
  <url>
    <loc>https://statementdog.com/blog/archives/20</loc>
    <lastmod>2025-01-01T00:00:00+08:00</lastmod>
  </url>
</urlset>
"""


EARNINGS_HTML = """
<html lang="zh-Hant">
<head>
  <title>泰瑞達 (TER) 2026 Q1 法說會逐字稿 - 財報狗</title>
  <meta name="description" content="泰瑞達 (TER) 2026Q1電話會議重點摘要和逐字稿。">
  <script type="application/ld+json">
  [{
    "@context": "https://schema.org",
    "@type": "NewsArticle",
    "headline": "泰瑞達 (TER) 2026 Q1 法說會逐字稿 - 財報狗",
    "datePublished": "2026-04-16T09:55:28+08:00",
    "dateModified": "2026-04-17T09:55:28+08:00",
    "url": "https://statementdog.com/analysis/TER/earnings_calls/312648"
  }]
  </script>
</head>
<body>
  <div id="analysis-app-meta-data" data-route="/TER/earnings_calls/312648" data-ticker="TER" data-ticker-name="TER 泰瑞達"></div>
  <h1>泰瑞達 (TER) 2026 Q1 法說會逐字稿</h1>
  <h2>內容摘要</h2>
  <p>Q1 2026 營收 $1.282B、non-GAAP EPS $2.56，均創歷史新高。</p>
  <h2>成長動能 &amp; 風險</h2>
  <p>AI 需求強勁，Q1 AI 相關營收占比近 70%。</p>
</body>
</html>
"""


@pytest.mark.asyncio
async def test_statementdog_source_requires_explicit_authorization():
    source = StatementDogSource(authorized=False)

    result = await source.refresh()

    assert result.status == "disabled"
    assert result.documents == []
    assert "authorization" in result.message.lower()


@pytest.mark.asyncio
async def test_statementdog_source_discovers_recent_authorized_urls_from_sitemap():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://statementdog.com/sitemap.xml.gz"
        return httpx.Response(200, content=gzip.compress(SITEMAP.encode("utf-8")))

    source = StatementDogSource(
        authorized=True,
        lookback_months=6,
        now=lambda: datetime(2026, 7, 3, tzinfo=UTC),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    urls = await source.discover()

    assert [item.url for item in urls] == [
        "https://statementdog.com/analysis/TER",
        "https://statementdog.com/blog/archives/14687",
    ]


def test_statementdog_parser_extracts_article_metadata_and_visible_text():
    document = parse_statementdog_html(
        "https://statementdog.com/analysis/TER/earnings_calls/312648",
        EARNINGS_HTML,
        captured_at=datetime(2026, 7, 3, 12, 0, tzinfo=UTC),
    )

    assert document.source_id == "statementdog"
    assert document.document_id == "analysis/TER/earnings_calls/312648"
    assert document.document_type == "earnings_call"
    assert document.ticker == "TER"
    assert document.company_name == "泰瑞達"
    assert document.title == "泰瑞達 (TER) 2026 Q1 法說會逐字稿 - 財報狗"
    assert document.published_at == datetime(2026, 4, 16, 1, 55, 28, tzinfo=UTC)
    assert "AI 需求強勁" in document.content
    assert document.summary == "泰瑞達 (TER) 2026Q1電話會議重點摘要和逐字稿。"


@pytest.mark.asyncio
async def test_statementdog_refresh_fetches_documents_and_reports_failures():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://statementdog.com/sitemap.xml.gz":
            return httpx.Response(200, content=gzip.compress(SITEMAP.encode("utf-8")))
        if url == "https://statementdog.com/analysis/TER":
            return httpx.Response(200, text=EARNINGS_HTML)
        return httpx.Response(503, text="temporary provider error")

    source = StatementDogSource(
        authorized=True,
        lookback_months=6,
        now=lambda: datetime(2026, 7, 3, tzinfo=UTC),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    result = await source.refresh()

    assert result.status == "degraded"
    assert result.discovered_count == 2
    assert result.fetched_count == 1
    assert result.failed_count == 1
    assert [document.ticker for document in result.documents] == ["TER"]
