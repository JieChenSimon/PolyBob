from datetime import UTC, datetime

import pytest

from libs.knowledge.models import KnowledgeDocument
from libs.knowledge.sources.base import SourceRefreshResult
from libs.knowledge.store import KnowledgeStore
from modules.knowledge_ingestion.service import KnowledgeIngestionService


def doc(document_id: str, content: str) -> KnowledgeDocument:
    return KnowledgeDocument(
        source_id="fixture",
        document_id=document_id,
        url=f"https://example.test/{document_id}",
        title=f"Document {document_id}",
        document_type="fixture",
        ticker=None,
        company_name=None,
        published_at=None,
        updated_at=None,
        captured_at=datetime(2026, 7, 3, tzinfo=UTC),
        language="en",
        summary="fixture summary",
        content=content,
        tags=[],
        metadata={},
    )


class FakeSource:
    source_id = "fixture"

    def __init__(self) -> None:
        self.calls = 0

    async def refresh(self):
        self.calls += 1
        return SourceRefreshResult(
            source_id=self.source_id,
            status="ok",
            documents=[doc("one", "AI research note"), doc("two", "market structure")],
            discovered_count=2,
            fetched_count=2,
            failed_count=0,
            message="ok",
        )


@pytest.mark.asyncio
async def test_manual_refresh_persists_documents_and_source_status(tmp_path):
    store = KnowledgeStore(tmp_path / "knowledge.sqlite3")
    source = FakeSource()
    service = KnowledgeIngestionService(store=store, sources=[source], enabled=False)

    result = await service.refresh_source("fixture")

    assert result["source_id"] == "fixture"
    assert result["status"] == "ok"
    assert result["inserted_count"] == 2
    assert source.calls == 1
    assert store.search(query="AI")[0].document_id == "one"
    assert store.source_statuses()[0].status == "ok"


@pytest.mark.asyncio
async def test_refresh_unknown_source_reports_clear_error(tmp_path):
    service = KnowledgeIngestionService(
        store=KnowledgeStore(tmp_path / "knowledge.sqlite3"),
        sources=[],
        enabled=False,
    )

    with pytest.raises(KeyError, match="unknown knowledge source"):
        await service.refresh_source("missing")


@pytest.mark.asyncio
async def test_disabled_background_start_does_not_refresh(tmp_path):
    source = FakeSource()
    service = KnowledgeIngestionService(
        store=KnowledgeStore(tmp_path / "knowledge.sqlite3"),
        sources=[source],
        enabled=False,
    )

    await service.start()
    await service.stop()

    assert source.calls == 0
