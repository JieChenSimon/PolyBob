from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from threading import BoundedSemaphore
from pathlib import Path
from typing import Any

from libs.db.job_store import JobStore


class TaskRunner:
    """Small synchronous runner with durable state and idempotent enqueue."""

    def __init__(self, db_path: str | Path, *, max_concurrency: int = 1) -> None:
        self.store = JobStore(db_path)
        if max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
        self._slots = BoundedSemaphore(max_concurrency)

    def run(self, *, job_id: str, idempotency_key: str, kind: str,
            payload: dict[str, Any], handler: Callable[[dict[str, Any]], Any],
            retries: int = 0, timeout_seconds: float | None = None) -> dict[str, Any]:
        if retries < 0 or (timeout_seconds is not None and timeout_seconds <= 0):
            raise ValueError("retries must be non-negative and timeout positive")
        job = self.store.enqueue(job_id=job_id, idempotency_key=idempotency_key, kind=kind, payload=payload)
        if job["status"] in {"succeeded", "cancelled"}:
            return job
        with self._slots:
            last_error = None
            for _ in range(retries + 1):
                self.store.transition(job["job_id"], "running")
                executor = ThreadPoolExecutor(max_workers=1)
                future = executor.submit(handler, payload)
                try:
                    future.result(timeout=timeout_seconds)
                    executor.shutdown(wait=True)
                    return self.store.transition(job["job_id"], "succeeded")
                except FutureTimeout:
                    future.cancel()
                    last_error = f"timeout after {timeout_seconds}s"
                except Exception as exc:  # noqa: BLE001 - persisted failure is the contract
                    last_error = str(exc) or exc.__class__.__name__
                finally:
                    executor.shutdown(wait=False, cancel_futures=True)
            return self.store.transition(job["job_id"], "failed", error=last_error)

    def cancel(self, job_id: str) -> dict[str, Any]:
        return self.store.transition(job_id, "cancelled")
