"""Provider-neutral source contracts for knowledge ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from libs.knowledge.models import KnowledgeDocument


@dataclass(frozen=True)
class DiscoveredUrl:
    url: str
    lastmod: datetime | None = None
    document_type: str | None = None


@dataclass(frozen=True)
class SourceRefreshResult:
    source_id: str
    status: str
    documents: list[KnowledgeDocument]
    discovered_count: int
    fetched_count: int
    failed_count: int
    message: str


class KnowledgeSource(Protocol):
    source_id: str

    async def discover(self) -> list[DiscoveredUrl]:
        ...

    async def refresh(self) -> SourceRefreshResult:
        ...
