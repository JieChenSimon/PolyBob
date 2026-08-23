"""Bounded JSON transport shared by discovery providers."""

from __future__ import annotations

from typing import Any

import httpx

from libs.data.http_client import build_bounded_async_client
from libs.networking import resolve_outbound_proxy


def build_provider_http_client(
    *,
    proxy: str | None = None,
    timeout_seconds: float = 10.0,
) -> httpx.AsyncClient:
    resolved_proxy = proxy if proxy is not None else resolve_outbound_proxy()
    return build_bounded_async_client(
        proxy=resolved_proxy,
        timeout=httpx.Timeout(timeout_seconds),
        follow_redirects=True,
        headers={"Accept-Encoding": "identity", "User-Agent": "polybob/0.1"},
    )


async def request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    **kwargs: Any,
) -> dict[str, Any] | list[Any]:
    response = await client.request(method, url, **kwargs)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, (dict, list)):
        raise ValueError(f"Expected JSON object or list from {url}")
    return payload
