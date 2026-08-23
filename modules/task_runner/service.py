from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from libs.db.job_store import JobStore


class TaskRunner:
    """Small synchronous runner with durable state and idempotent enqueue."""

    def __init__(self, db_path: str | Path) -> None:
        self.store = JobStore(db_path)

    def run(self, *, job_id: str, idempotency_key: str, kind: str,
            payload: dict[str, Any], handler: Callable[[dict[str, Any]], Any]) -> dict[str, Any]:
        job = self.store.enqueue(job_id=job_id, idempotency_key=idempotency_key, kind=kind, payload=payload)
        if job["status"] in {"succeeded", "cancelled"}:
            return job
        self.store.transition(job["job_id"], "running")
        try:
            handler(payload)
        except Exception as exc:  # noqa: BLE001 - persisted failure is the contract
            return self.store.transition(job["job_id"], "failed", error=str(exc))
        return self.store.transition(job["job_id"], "succeeded")

    def cancel(self, job_id: str) -> dict[str, Any]:
        return self.store.transition(job_id, "cancelled")
