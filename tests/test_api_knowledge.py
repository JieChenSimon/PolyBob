from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

import apps.api.main as api
from libs.knowledge.models import KnowledgeDocument
from libs.knowledge.store import KnowledgeStore


def make_document() -> KnowledgeDocument:
    return KnowledgeDocument(
        source_id="statementdog",
        document_id="analysis/TER",
        url="https://statementdog.com/analysis/TER",
        title="泰瑞達 AI 測試",
        document_type="company_analysis",
        ticker="TER",
        company_name="泰瑞達",
        published_at=datetime(2026, 4, 16, tzinfo=UTC),
        updated_at=None,
        captured_at=datetime(2026, 7, 3, tzinfo=UTC),
        language="zh-Hant",
        summary="AI 測試需求強勁",
        content="AI 測試需求強勁，營收創高。",
        tags=["TER"],
        metadata={},
    )


class FakeKnowledgeService:
    def __init__(self, store: KnowledgeStore) -> None:
        self.store = store

    def search(self, **kwargs):
        return self.store.search(**kwargs)

    def recent(self, **kwargs):
        return self.store.recent(**kwargs)

    def source_statuses(self):
        return self.store.source_statuses()

    async def refresh_source(self, source_id: str):
        return {
            "source_id": source_id,
            "status": "ok",
            "inserted_count": 0,
            "updated_count": 0,
            "failed_count": 0,
            "message": "ok",
        }


@pytest.fixture
def knowledge_api(monkeypatch, tmp_path):
    store = KnowledgeStore(tmp_path / "knowledge.sqlite3")
    store.init()
    store.upsert_document(make_document())
    service = FakeKnowledgeService(store)
    monkeypatch.setattr(api, "knowledge_ingestion", service)
    return service


@pytest.mark.asyncio
async def test_knowledge_search_api_returns_serializable_results(knowledge_api):
    payload = await api.search_knowledge(q="AI", source="statementdog", ticker="TER")

    assert payload["count"] == 1
    assert payload["results"][0]["title"] == "泰瑞達 AI 測試"
    assert payload["results"][0]["published_at"] == "2026-04-16T00:00:00+00:00"


@pytest.mark.asyncio
async def test_knowledge_recent_api_returns_latest_documents(knowledge_api):
    payload = await api.get_recent_knowledge(source="statementdog", limit=5)

    assert payload["count"] == 1
    assert payload["results"][0]["document_id"] == "analysis/TER"


@pytest.mark.asyncio
async def test_knowledge_status_requires_service(monkeypatch):
    monkeypatch.setattr(api, "knowledge_ingestion", None)

    with pytest.raises(HTTPException) as exc_info:
        await api.get_knowledge_sources()

    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_knowledge_manual_refresh_uses_service(knowledge_api):
    payload = await api.refresh_knowledge_source("statementdog")

    assert payload["source_id"] == "statementdog"
    assert payload["status"] == "ok"
