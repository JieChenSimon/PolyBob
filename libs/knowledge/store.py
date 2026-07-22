"""SQLite-backed local research knowledge store."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from libs.config import get_settings
from libs.knowledge.models import (
    KnowledgeDocument,
    KnowledgeSearchResult,
    SourceRunStatus,
    normalize_dt,
    parse_dt,
)


class KnowledgeStore:
    def __init__(self, db_path: str | Path | None = None, *, use_fts: bool = True) -> None:
        self.db_path = Path(db_path or get_settings().polybob_db_path).expanduser()
        self.use_fts = use_fts
        self._fts_available: bool | None = None

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def init(self) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    document_type TEXT NOT NULL,
                    ticker TEXT,
                    company_name TEXT,
                    published_at TEXT,
                    updated_at TEXT,
                    captured_at TEXT NOT NULL,
                    language TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL DEFAULT '',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    stored_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(source_id, document_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_source_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    discovered_count INTEGER NOT NULL DEFAULT 0,
                    fetched_count INTEGER NOT NULL DEFAULT 0,
                    inserted_count INTEGER NOT NULL DEFAULT 0,
                    updated_count INTEGER NOT NULL DEFAULT 0,
                    failed_count INTEGER NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT ''
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_documents_source ON knowledge_documents(source_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_documents_type ON knowledge_documents(document_type)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_documents_ticker ON knowledge_documents(ticker)"
            )
            self._ensure_fts(connection)

    def _ensure_fts(self, connection: sqlite3.Connection) -> bool:
        if not self.use_fts:
            self._fts_available = False
            return False
        try:
            connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_documents_fts
                USING fts5(
                    source_id UNINDEXED,
                    document_id UNINDEXED,
                    title,
                    summary,
                    content,
                    tags
                )
                """
            )
        except sqlite3.OperationalError:
            self._fts_available = False
            return False
        self._fts_available = True
        return True

    def upsert_document(self, document: KnowledgeDocument) -> str:
        self.init()
        tags_json = json.dumps(document.tags, ensure_ascii=False, sort_keys=True)
        metadata_json = json.dumps(document.metadata, ensure_ascii=False, sort_keys=True)
        with self.connect() as connection:
            existing = connection.execute(
                """
                SELECT id, content_hash
                FROM knowledge_documents
                WHERE source_id = ? AND document_id = ?
                """,
                (document.source_id, document.document_id),
            ).fetchone()
            action = "inserted" if existing is None else "updated"
            if existing is not None and existing["content_hash"] == document.content_hash:
                action = "unchanged"

            now = datetime.now(UTC).isoformat()
            connection.execute(
                """
                INSERT INTO knowledge_documents (
                    source_id, document_id, url, title, document_type, ticker,
                    company_name, published_at, updated_at, captured_at, language,
                    summary, content, tags_json, metadata_json, content_hash, stored_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id, document_id) DO UPDATE SET
                    url = excluded.url,
                    title = excluded.title,
                    document_type = excluded.document_type,
                    ticker = excluded.ticker,
                    company_name = excluded.company_name,
                    published_at = excluded.published_at,
                    updated_at = excluded.updated_at,
                    captured_at = excluded.captured_at,
                    language = excluded.language,
                    summary = excluded.summary,
                    content = excluded.content,
                    tags_json = excluded.tags_json,
                    metadata_json = excluded.metadata_json,
                    content_hash = excluded.content_hash,
                    stored_at = excluded.stored_at
                """,
                (
                    document.source_id,
                    document.document_id,
                    document.url,
                    document.title,
                    document.document_type,
                    document.ticker,
                    document.company_name,
                    normalize_dt(document.published_at),
                    normalize_dt(document.updated_at),
                    normalize_dt(document.captured_at),
                    document.language,
                    document.summary,
                    document.content,
                    tags_json,
                    metadata_json,
                    document.content_hash,
                    now,
                ),
            )
            if self._ensure_fts(connection):
                connection.execute(
                    """
                    DELETE FROM knowledge_documents_fts
                    WHERE source_id = ? AND document_id = ?
                    """,
                    (document.source_id, document.document_id),
                )
                connection.execute(
                    """
                    INSERT INTO knowledge_documents_fts (
                        source_id, document_id, title, summary, content, tags
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document.source_id,
                        document.document_id,
                        document.title,
                        document.summary,
                        document.content,
                        " ".join(document.tags),
                    ),
                )
            return action

    def recent(
        self,
        *,
        source_id: str | None = None,
        limit: int = 20,
    ) -> list[KnowledgeSearchResult]:
        self.init()
        filters: list[str] = []
        params: list[Any] = []
        if source_id:
            filters.append("source_id = ?")
            params.append(source_id)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        params.append(max(1, min(limit, 100)))
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT *
                FROM knowledge_documents
                {where}
                ORDER BY COALESCE(updated_at, published_at, captured_at) DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_result(row, snippet=row["summary"] or row["content"][:240]) for row in rows]

    def search(
        self,
        *,
        query: str = "",
        source_id: str | None = None,
        document_type: str | None = None,
        ticker: str | None = None,
        limit: int = 20,
    ) -> list[KnowledgeSearchResult]:
        self.init()
        clean_query = query.strip()
        if clean_query and self._fts_available:
            try:
                return self._search_fts(
                    query=clean_query,
                    source_id=source_id,
                    document_type=document_type,
                    ticker=ticker,
                    limit=limit,
                )
            except sqlite3.OperationalError:
                pass
        return self._search_like(
            query=clean_query,
            source_id=source_id,
            document_type=document_type,
            ticker=ticker,
            limit=limit,
        )

    def _search_fts(
        self,
        *,
        query: str,
        source_id: str | None,
        document_type: str | None,
        ticker: str | None,
        limit: int,
    ) -> list[KnowledgeSearchResult]:
        fts_query = " OR ".join(part.replace('"', "") for part in query.split() if part.strip()) or query
        filters = ["f.knowledge_documents_fts MATCH ?"]
        params: list[Any] = [fts_query]
        if source_id:
            filters.append("d.source_id = ?")
            params.append(source_id)
        if document_type:
            filters.append("d.document_type = ?")
            params.append(document_type)
        if ticker:
            filters.append("d.ticker = ?")
            params.append(ticker.upper())
        params.append(max(1, min(limit, 100)))
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT d.*,
                       snippet(knowledge_documents_fts, 4, '<mark>', '</mark>', '...', 24) AS snippet
                FROM knowledge_documents_fts AS f
                JOIN knowledge_documents AS d
                  ON d.source_id = f.source_id AND d.document_id = f.document_id
                WHERE {' AND '.join(filters)}
                ORDER BY bm25(knowledge_documents_fts)
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_result(row, snippet=row["snippet"] or row["summary"]) for row in rows]

    def _search_like(
        self,
        *,
        query: str,
        source_id: str | None,
        document_type: str | None,
        ticker: str | None,
        limit: int,
    ) -> list[KnowledgeSearchResult]:
        filters: list[str] = []
        params: list[Any] = []
        if query:
            like = f"%{query}%"
            filters.append("(title LIKE ? OR summary LIKE ? OR content LIKE ? OR tags_json LIKE ?)")
            params.extend([like, like, like, like])
        if source_id:
            filters.append("source_id = ?")
            params.append(source_id)
        if document_type:
            filters.append("document_type = ?")
            params.append(document_type)
        if ticker:
            filters.append("ticker = ?")
            params.append(ticker.upper())
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        params.append(max(1, min(limit, 100)))
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT *
                FROM knowledge_documents
                {where}
                ORDER BY COALESCE(updated_at, published_at, captured_at) DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_result(row, snippet=self._build_like_snippet(row, query)) for row in rows]

    def record_source_run(
        self,
        *,
        source_id: str,
        status: str,
        started_at: datetime,
        finished_at: datetime | None,
        discovered_count: int,
        fetched_count: int,
        inserted_count: int,
        updated_count: int,
        failed_count: int,
        message: str,
    ) -> None:
        self.init()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO knowledge_source_runs (
                    source_id, status, started_at, finished_at, discovered_count,
                    fetched_count, inserted_count, updated_count, failed_count, message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    status,
                    normalize_dt(started_at),
                    normalize_dt(finished_at),
                    discovered_count,
                    fetched_count,
                    inserted_count,
                    updated_count,
                    failed_count,
                    message,
                ),
            )

    def source_statuses(self) -> list[SourceRunStatus]:
        self.init()
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT r.*
                FROM knowledge_source_runs AS r
                JOIN (
                    SELECT source_id, MAX(id) AS id
                    FROM knowledge_source_runs
                    GROUP BY source_id
                ) AS latest ON latest.id = r.id
                ORDER BY r.source_id
                """
            ).fetchall()
        return [self._row_to_status(row) for row in rows]

    def _row_to_result(self, row: sqlite3.Row, *, snippet: str) -> KnowledgeSearchResult:
        return KnowledgeSearchResult(
            source_id=row["source_id"],
            document_id=row["document_id"],
            url=row["url"],
            title=row["title"],
            document_type=row["document_type"],
            ticker=row["ticker"],
            company_name=row["company_name"],
            published_at=parse_dt(row["published_at"]),
            updated_at=parse_dt(row["updated_at"]),
            captured_at=parse_dt(row["captured_at"]) or datetime.now(UTC),
            language=row["language"],
            summary=row["summary"],
            snippet=snippet,
            tags=json.loads(row["tags_json"] or "[]"),
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    def _row_to_status(self, row: sqlite3.Row) -> SourceRunStatus:
        return SourceRunStatus(
            source_id=row["source_id"],
            status=row["status"],
            started_at=parse_dt(row["started_at"]) or datetime.now(UTC),
            finished_at=parse_dt(row["finished_at"]),
            discovered_count=int(row["discovered_count"]),
            fetched_count=int(row["fetched_count"]),
            inserted_count=int(row["inserted_count"]),
            updated_count=int(row["updated_count"]),
            failed_count=int(row["failed_count"]),
            message=row["message"],
        )

    @staticmethod
    def _build_like_snippet(row: sqlite3.Row, query: str) -> str:
        text = row["summary"] or row["content"] or ""
        if not query:
            return text[:240]
        index = text.lower().find(query.lower())
        if index < 0:
            return text[:240]
        start = max(0, index - 80)
        end = min(len(text), index + len(query) + 160)
        prefix = "..." if start else ""
        suffix = "..." if end < len(text) else ""
        return f"{prefix}{text[start:end]}{suffix}"
