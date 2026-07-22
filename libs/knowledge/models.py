"""Typed contracts for local research knowledge documents."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def utc_now() -> datetime:
    return datetime.now(UTC)


def normalize_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True)
class KnowledgeDocument:
    source_id: str
    document_id: str
    url: str
    title: str
    document_type: str
    ticker: str | None
    company_name: str | None
    published_at: datetime | None
    updated_at: datetime | None
    captured_at: datetime
    language: str
    summary: str
    content: str
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        payload = {
            "title": self.title,
            "summary": self.summary,
            "content": self.content,
            "tags": self.tags,
            "metadata": self.metadata,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class KnowledgeSearchResult:
    source_id: str
    document_id: str
    url: str
    title: str
    document_type: str
    ticker: str | None
    company_name: str | None
    published_at: datetime | None
    updated_at: datetime | None
    captured_at: datetime
    language: str
    summary: str
    snippet: str
    tags: list[str]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class SourceRunStatus:
    source_id: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    discovered_count: int
    fetched_count: int
    inserted_count: int
    updated_count: int
    failed_count: int
    message: str
