"""Shared plumbing for the API: logging, the HTTP client, and the response cache.

``apps/api/main.py`` had grown to 2,883 lines and 62 routes, which made every
route group depend on every other one and left no seam to extract along. This
module is that seam: the pieces every route group needs, owned in one place so a
router can import them without importing the application.

Nothing here knows about routes or business logic. If something needs a service,
it belongs with the routes that use it, not here.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

import httpx
import structlog

logger = structlog.get_logger()

_api_response_cache: dict[str, dict[str, Any]] = {}
_api_response_locks: dict[str, asyncio.Lock] = {}
_API_RESPONSE_CACHE_MAX_ENTRIES = 256

_shared_http_client: httpx.AsyncClient | None = None


def get_shared_http_client() -> httpx.AsyncClient:
    """返回进程级共享的 AsyncClient；缺失时懒加载创建（便于无 lifespan 的测试）。"""
    global _shared_http_client
    if _shared_http_client is None or _shared_http_client.is_closed:
        _shared_http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(4, connect=2),
            headers={"User-Agent": "PolyBob/0.1"},
        )
    return _shared_http_client


async def close_shared_http_client() -> None:
    global _shared_http_client
    client, _shared_http_client = _shared_http_client, None
    if client is not None and not client.is_closed:
        await client.aclose()


def _evict_expired_api_cache_entries(now: float, active_key: str) -> None:
    """插入新缓存前清理过期条目（及其锁），并对总量做硬上限。"""
    for key in [
        key
        for key, entry in _api_response_cache.items()
        if entry["expires_at"] <= now and key != active_key
    ]:
        _api_response_cache.pop(key, None)
        _api_response_locks.pop(key, None)

    overflow = len(_api_response_cache) - _API_RESPONSE_CACHE_MAX_ENTRIES
    if overflow > 0:
        for key in sorted(
            _api_response_cache,
            key=lambda cache_key: _api_response_cache[cache_key]["expires_at"],
        ):
            if overflow <= 0:
                break
            if key == active_key:
                continue
            _api_response_cache.pop(key, None)
            _api_response_locks.pop(key, None)
            overflow -= 1


async def cached_api_response(
    key: str,
    ttl_seconds: float,
    loader: Callable[[], Awaitable[dict]],
) -> dict:
    now = time.monotonic()
    cached = _api_response_cache.get(key)
    if cached and cached["expires_at"] > now:
        return cached["value"]

    lock = _api_response_locks.setdefault(key, asyncio.Lock())
    async with lock:
        now = time.monotonic()
        cached = _api_response_cache.get(key)
        if cached and cached["expires_at"] > now:
            return cached["value"]

        value = await loader()
        now = time.monotonic()
        _evict_expired_api_cache_entries(now, key)
        _api_response_cache[key] = {
            "expires_at": now + ttl_seconds,
            "value": value,
        }
        return value


def clear_api_response_cache() -> None:
    _api_response_cache.clear()
    _api_response_locks.clear()

__all__ = [
    "cached_api_response",
    "clear_api_response_cache",
    "close_shared_http_client",
    "get_shared_http_client",
    "logger",
]
