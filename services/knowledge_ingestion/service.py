"""Background orchestration for extensible research knowledge ingestion."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from libs.knowledge.sources.base import KnowledgeSource
from libs.knowledge.store import KnowledgeStore


class KnowledgeIngestionService:
    def __init__(
        self,
        *,
        store: KnowledgeStore,
        sources: list[KnowledgeSource],
        enabled: bool,
        interval_seconds: float = 3600.0,
    ) -> None:
        self.store = store
        self.sources = {source.source_id: source for source in sources}
        self.enabled = enabled
        self.interval_seconds = max(float(interval_seconds), 60.0)
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        self.store.init()
        if not self.enabled or self._task is not None:
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _loop(self) -> None:
        while not self._stopping.is_set():
            await self.refresh_all()
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                continue

    async def refresh_all(self) -> list[dict[str, Any]]:
        results = []
        for source_id in self.sources:
            results.append(await self.refresh_source(source_id))
        return results

    async def refresh_source(self, source_id: str) -> dict[str, Any]:
        source = self.sources.get(source_id)
        if source is None:
            raise KeyError(f"unknown knowledge source: {source_id}")
        started_at = datetime.now(UTC)
        inserted_count = 0
        updated_count = 0
        failed_count = 0
        status = "error"
        message = ""
        discovered_count = 0
        fetched_count = 0
        try:
            result = await source.refresh()
            status = result.status
            message = result.message
            discovered_count = result.discovered_count
            fetched_count = result.fetched_count
            failed_count = result.failed_count
            for document in result.documents:
                action = self.store.upsert_document(document)
                if action == "inserted":
                    inserted_count += 1
                elif action == "updated":
                    updated_count += 1
        except Exception as exc:
            failed_count += 1
            message = str(exc) or exc.__class__.__name__
            status = "error"

        finished_at = datetime.now(UTC)
        self.store.record_source_run(
            source_id=source_id,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            discovered_count=discovered_count,
            fetched_count=fetched_count,
            inserted_count=inserted_count,
            updated_count=updated_count,
            failed_count=failed_count,
            message=message,
        )
        return {
            "source_id": source_id,
            "status": status,
            "discovered_count": discovered_count,
            "fetched_count": fetched_count,
            "inserted_count": inserted_count,
            "updated_count": updated_count,
            "failed_count": failed_count,
            "message": message,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
        }

    def search(self, **kwargs):
        return self.store.search(**kwargs)

    def recent(self, **kwargs):
        return self.store.recent(**kwargs)

    def source_statuses(self):
        return self.store.source_statuses()
