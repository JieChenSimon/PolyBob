"""Durable, bounded provider fetches for real-data research.

The research pipeline must be slow-but-complete when a provider is slow.  This
module provides two small primitives: immutable response caching and an atomic
JSON checkpoint.  A failed request is retried with bounded exponential backoff;
after the retry budget is exhausted the error remains visible to the caller.
No missing response is converted into synthetic data.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from libs.data.http_client import HttpFetchError, http_get_bytes


@dataclass(frozen=True)
class FetchPolicy:
    attempts: int = 4
    timeout_seconds: float = 30.0
    initial_backoff_seconds: float = 0.5
    max_backoff_seconds: float = 15.0


def cache_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def fetch_cached_bytes(
    url: str,
    *,
    cache_dir: str | Path,
    policy: FetchPolicy | None = None,
    headers: dict[str, str] | None = None,
    stream: bool = False,
    fetcher: Callable[..., bytes] = http_get_bytes,
    dataset: str | None = None,
    source: str | None = None,
) -> bytes:
    """Fetch an immutable provider response, reusing a verified local copy."""
    policy = policy or FetchPolicy()
    root = Path(cache_dir)
    key = cache_key(url)
    payload_path = root / f"{key}.body"
    meta_path = root / f"{key}.json"
    if payload_path.exists() and payload_path.stat().st_size > 0:
        payload = payload_path.read_bytes()
        if dataset:
            from libs.data.data_lake import record_raw
            record_raw(dataset, payload, source=source or url.split('/')[2], request=url)
        return payload

    root.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(1, max(1, policy.attempts) + 1):
        try:
            payload = fetcher(
                url,
                timeout=policy.timeout_seconds,
                headers=headers,
                stream=stream,
            )
            if not payload:
                raise HttpFetchError(f"{url} -> empty response")
            tmp = payload_path.with_suffix(".body.tmp")
            tmp.write_bytes(payload)
            tmp.replace(payload_path)
            if dataset:
                from libs.data.data_lake import record_raw
                record_raw(dataset, payload, source=source or url.split('/')[2], request=url)
            meta_path.write_text(json.dumps({
                "url": url,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "fetched_at": time.time(),
                "attempt": attempt,
            }, indent=2), encoding="utf-8")
            return payload
        except Exception as exc:  # provider-specific errors are intentionally preserved
            last_error = exc
            if attempt >= max(1, policy.attempts):
                break
            delay = min(
                policy.max_backoff_seconds,
                policy.initial_backoff_seconds * (2 ** (attempt - 1)),
            )
            time.sleep(delay * (0.8 + random.random() * 0.4))
    raise HttpFetchError(f"{url} -> exhausted {policy.attempts} attempts: {last_error}") from last_error


def load_checkpoint(path: str | Path, *, spec: str) -> dict[str, Any]:
    """Load a checkpoint only when it belongs to the current collector spec."""
    target = Path(path)
    if not target.exists():
        return {"spec": spec, "items": {}}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"spec": spec, "items": {}}
    if payload.get("spec") != spec or not isinstance(payload.get("items"), dict):
        return {"spec": spec, "items": {}}
    return payload


def save_checkpoint(path: str | Path, payload: dict[str, Any]) -> None:
    """Atomically persist progress so an interrupted run resumes safely."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(target)


__all__ = ["FetchPolicy", "cache_key", "fetch_cached_bytes", "load_checkpoint", "save_checkpoint"]
