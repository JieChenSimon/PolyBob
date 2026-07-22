"""StatementDog knowledge source adapter."""

from __future__ import annotations

import gzip
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html import unescape
from html.parser import HTMLParser
from typing import Callable, Iterable
from urllib.parse import urlparse

import httpx

from libs.knowledge.models import KnowledgeDocument, utc_now
from libs.knowledge.sources.base import DiscoveredUrl, SourceRefreshResult


STATEMENTDOG_BASE_URL = "https://statementdog.com"
STATEMENTDOG_SITEMAP_URL = "https://statementdog.com/sitemap.xml.gz"


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _document_type_for_url(url: str) -> str | None:
    path = urlparse(url).path.strip("/")
    if re.match(r"^analysis/[^/]+/earnings_calls/\d+$", path):
        return "earnings_call"
    if re.match(r"^analysis/[^/]+$", path):
        return "company_analysis"
    if re.match(r"^blog/archives/\d+$", path):
        return "blog"
    return None


def _document_id_for_url(url: str) -> str:
    return urlparse(url).path.strip("/") or "root"


class _StatementDogHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.meta_description = ""
        self.json_ld_blocks: list[str] = []
        self.analysis_metadata: dict[str, str] = {}
        self._capture_title = False
        self._capture_script = False
        self._script_type = ""
        self._script_parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key: value or "" for key, value in attrs}
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
        if tag == "script":
            self._script_type = attrs_dict.get("type", "")
            self._capture_script = self._script_type == "application/ld+json"
            self._script_parts = []
        if tag == "title":
            self._capture_title = True
        if tag == "meta" and attrs_dict.get("name") == "description":
            self.meta_description = unescape(attrs_dict.get("content", "")).strip()
        if attrs_dict.get("id") == "analysis-app-meta-data":
            self.analysis_metadata = {
                key.replace("data-", "").replace("-", "_"): value
                for key, value in attrs_dict.items()
                if key.startswith("data-")
            }

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._capture_title = False
        if tag == "script":
            if self._capture_script:
                self.json_ld_blocks.append("".join(self._script_parts).strip())
            self._capture_script = False
            self._script_type = ""
            self._script_parts = []
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._capture_script:
            self._script_parts.append(data)
            return
        if self._capture_title:
            self.title_parts.append(data)
            return
        if self._skip_depth:
            return
        cleaned = re.sub(r"\s+", " ", unescape(data)).strip()
        if cleaned:
            self.text_parts.append(cleaned)

    @property
    def title(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self.title_parts)).strip()

    @property
    def visible_text(self) -> str:
        return "\n".join(self.text_parts)


def _flatten_json_ld(blocks: Iterable[str]) -> list[dict]:
    items: list[dict] = []
    for block in blocks:
        if not block:
            continue
        try:
            parsed = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            items.extend(item for item in parsed if isinstance(item, dict))
        elif isinstance(parsed, dict):
            items.append(parsed)
    return items


def _first_article_metadata(items: list[dict]) -> dict:
    for item in items:
        item_type = item.get("@type")
        if item_type in {"NewsArticle", "Article", "WebPage"}:
            return item
    return items[0] if items else {}


def _ticker_from_url_or_metadata(url: str, metadata: dict[str, str], title: str) -> str | None:
    if metadata.get("ticker"):
        return metadata["ticker"].upper()
    match = re.search(r"/analysis/([^/]+)", urlparse(url).path)
    if match:
        return match.group(1).upper()
    title_match = re.search(r"\(([A-Z0-9.]{1,12})\)", title)
    return title_match.group(1).upper() if title_match else None


def _company_name_from_metadata(metadata: dict[str, str], ticker: str | None) -> str | None:
    ticker_name = metadata.get("ticker_name", "").strip()
    if ticker_name and ticker:
        return ticker_name.replace(ticker, "", 1).strip() or None
    return ticker_name or None


def parse_statementdog_html(url: str, html: str, *, captured_at: datetime | None = None) -> KnowledgeDocument:
    parser = _StatementDogHTMLParser()
    parser.feed(html)
    json_ld_items = _flatten_json_ld(parser.json_ld_blocks)
    article = _first_article_metadata(json_ld_items)
    title = str(article.get("headline") or article.get("name") or parser.title or url).strip()
    ticker = _ticker_from_url_or_metadata(url, parser.analysis_metadata, title)
    company_name = _company_name_from_metadata(parser.analysis_metadata, ticker)
    document_type = _document_type_for_url(url) or "web_page"
    content = parser.visible_text
    summary = parser.meta_description or "\n".join(content.splitlines()[:3])[:500]
    tags = [document_type]
    if ticker:
        tags.append(ticker)

    return KnowledgeDocument(
        source_id="statementdog",
        document_id=_document_id_for_url(url),
        url=url,
        title=title,
        document_type=document_type,
        ticker=ticker,
        company_name=company_name,
        published_at=_parse_datetime(str(article.get("datePublished") or "")),
        updated_at=_parse_datetime(str(article.get("dateModified") or "")),
        captured_at=captured_at or utc_now(),
        language="zh-Hant",
        summary=summary,
        content=content,
        tags=tags,
        metadata={
            "provider": "statementdog",
            "json_ld_types": [
                str(item.get("@type")) for item in json_ld_items if item.get("@type")
            ],
        },
    )


@dataclass
class StatementDogSource:
    authorized: bool
    lookback_months: int = 6
    concurrency: int = 3
    sitemap_url: str = STATEMENTDOG_SITEMAP_URL
    client: httpx.AsyncClient | None = None
    now: Callable[[], datetime] = utc_now

    source_id: str = "statementdog"

    async def discover(self) -> list[DiscoveredUrl]:
        if not self.authorized:
            return []
        client = self._client()
        response = await client.get(self.sitemap_url, timeout=30)
        response.raise_for_status()
        content = response.content
        if self.sitemap_url.endswith(".gz"):
            content = gzip.decompress(content)
        root = ET.fromstring(content)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        cutoff = self.now().astimezone(UTC) - timedelta(days=max(self.lookback_months, 1) * 31)
        discovered: list[DiscoveredUrl] = []
        for item in root.findall("sm:url", ns):
            loc = item.findtext("sm:loc", default="", namespaces=ns).strip()
            document_type = _document_type_for_url(loc)
            if document_type is None:
                continue
            lastmod = _parse_datetime(item.findtext("sm:lastmod", default="", namespaces=ns))
            if lastmod and lastmod < cutoff:
                continue
            discovered.append(DiscoveredUrl(url=loc, lastmod=lastmod, document_type=document_type))
        return discovered

    async def refresh(self) -> SourceRefreshResult:
        if not self.authorized:
            return SourceRefreshResult(
                source_id=self.source_id,
                status="disabled",
                documents=[],
                discovered_count=0,
                fetched_count=0,
                failed_count=0,
                message="StatementDog crawl authorization is disabled.",
            )
        try:
            discovered = await self.discover()
        except Exception as exc:
            return SourceRefreshResult(
                source_id=self.source_id,
                status="error",
                documents=[],
                discovered_count=0,
                fetched_count=0,
                failed_count=1,
                message=f"sitemap discovery failed: {exc}",
            )

        documents: list[KnowledgeDocument] = []
        failed_count = 0
        client = self._client()
        for discovered_url in discovered:
            try:
                response = await client.get(discovered_url.url, timeout=30)
                response.raise_for_status()
                documents.append(
                    parse_statementdog_html(
                        discovered_url.url,
                        response.text,
                        captured_at=self.now().astimezone(UTC),
                    )
                )
            except Exception:
                failed_count += 1

        status = "ok" if failed_count == 0 else "degraded"
        return SourceRefreshResult(
            source_id=self.source_id,
            status=status,
            documents=documents,
            discovered_count=len(discovered),
            fetched_count=len(documents),
            failed_count=failed_count,
            message="ok" if failed_count == 0 else f"{failed_count} documents failed to fetch or parse",
        )

    def _client(self) -> httpx.AsyncClient:
        if self.client is not None:
            return self.client
        headers = {
            "User-Agent": "PolyBobResearchBot/0.1 (+authorized local research ingestion)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        self.client = httpx.AsyncClient(headers=headers, follow_redirects=True)
        return self.client
