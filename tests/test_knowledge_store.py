from datetime import UTC, datetime, timedelta

from libs.knowledge.models import KnowledgeDocument
from libs.knowledge.store import KnowledgeStore


def document(
    document_id: str,
    *,
    title: str,
    content: str,
    ticker: str | None = None,
    captured_at: datetime | None = None,
) -> KnowledgeDocument:
    return KnowledgeDocument(
        source_id="statementdog",
        document_id=document_id,
        url=f"https://statementdog.com/analysis/{document_id}",
        title=title,
        document_type="company_analysis",
        ticker=ticker,
        company_name=None,
        published_at=None,
        updated_at=None,
        captured_at=captured_at or datetime(2026, 7, 3, 12, 0, tzinfo=UTC),
        language="zh-Hant",
        summary="",
        content=content,
        tags=["semiconductor"] if ticker else [],
        metadata={"source": "fixture"},
    )


def test_store_initializes_idempotently_and_upserts_documents(tmp_path):
    db_path = tmp_path / "knowledge.sqlite3"
    store = KnowledgeStore(db_path)
    store.init()
    store.init()

    first = store.upsert_document(document("TER", title="泰瑞達 AI 測試", content="AI 測試需求強勁", ticker="TER"))
    second = store.upsert_document(document("TER", title="泰瑞達 AI 測試更新", content="AI 需求延續", ticker="TER"))

    assert first == "inserted"
    assert second == "updated"

    recent = store.recent(limit=10)
    assert len(recent) == 1
    assert recent[0].title == "泰瑞達 AI 測試更新"
    assert recent[0].ticker == "TER"


def test_store_searches_full_text_and_filters_by_source_type_and_ticker(tmp_path):
    store = KnowledgeStore(tmp_path / "knowledge.sqlite3")
    store.init()
    store.upsert_document(document("TER", title="泰瑞達 AI 測試", content="AI 測試需求強勁", ticker="TER"))
    store.upsert_document(document("AAOI", title="光通訊更新", content="資料中心光通訊需求", ticker="AAOI"))

    results = store.search(query="AI", source_id="statementdog", document_type="company_analysis", ticker="TER")

    assert [result.document_id for result in results] == ["TER"]
    assert results[0].snippet


def test_store_search_falls_back_when_fts_is_disabled(tmp_path):
    store = KnowledgeStore(tmp_path / "knowledge.sqlite3", use_fts=False)
    store.init()
    store.upsert_document(document("PSMT", title="PriceSmart 財報", content="會員制零售營收改善", ticker="PSMT"))

    results = store.search(query="零售")

    assert [result.document_id for result in results] == ["PSMT"]


def test_source_run_status_records_last_sync_summary(tmp_path):
    store = KnowledgeStore(tmp_path / "knowledge.sqlite3")
    store.init()
    started = datetime(2026, 7, 3, 10, 0, tzinfo=UTC)
    finished = started + timedelta(seconds=3)

    store.record_source_run(
        source_id="statementdog",
        status="ok",
        started_at=started,
        finished_at=finished,
        discovered_count=4,
        fetched_count=3,
        inserted_count=2,
        updated_count=1,
        failed_count=1,
        message="one timeout",
    )

    statuses = store.source_statuses()

    assert statuses[0].source_id == "statementdog"
    assert statuses[0].status == "ok"
    assert statuses[0].discovered_count == 4
    assert statuses[0].message == "one timeout"
