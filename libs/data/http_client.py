"""One pooled HTTP session for every provider fetch in the project.

Each data module used to call ``urllib.request.urlopen`` directly, which opens a
fresh TCP connection per request and never reuses one. On a long-running API
process that showed up as leaked descriptors — 15 sockets sitting in ``CLOSED``
against 5 live ones after 19 hours — and, with a system-wide proxy in front of
it, as a steadily growing pile of tunnel connections. Persistent connections are
not free when the machine tries to sleep: macOS keeps servicing their TCP
keepalives, waking every few seconds to do it.

So the pool here is deliberately **small and bounded** rather than as large as
possible. The goal is not maximum throughput — these are cached, low-rate
provider calls — it is to hold as few sockets open as possible while still
avoiding a new handshake for every request:

- ``pool_maxsize`` caps how many sockets can be alive at once.
- ``pool_block`` makes a burst wait for a free connection instead of quietly
  opening extra ones outside the pool, which is how the unbounded growth
  happened in the first place.
- The session is closed at interpreter exit, so descriptors are released even
  when a long-lived process is killed rather than shut down cleanly.

Failures are surfaced, never swallowed: callers convert the raised
:class:`HttpFetchError` into their own domain error so an outage stays visible
instead of turning into fabricated data.
"""

from __future__ import annotations

import atexit
import threading
from typing import Any, Mapping

import requests
from requests.adapters import HTTPAdapter

DEFAULT_UA = "Mozilla/5.0 (PolyBob real-data research)"

# Small on purpose — see the module docstring. Four hosts covers OKX, Yahoo,
# Tencent and the SEC, which is every provider this project talks to.
POOL_CONNECTIONS = 4
POOL_MAXSIZE = 8

_session: requests.Session | None = None
_lock = threading.Lock()


class HttpFetchError(RuntimeError):
    """A provider request failed. Callers re-raise as their own domain error."""


def get_session() -> requests.Session:
    """The process-wide pooled session, created on first use."""
    global _session
    with _lock:
        if _session is None:
            session = requests.Session()
            adapter = HTTPAdapter(
                pool_connections=POOL_CONNECTIONS,
                pool_maxsize=POOL_MAXSIZE,
                pool_block=True,
                max_retries=0,      # retries are a caller policy, not a transport one
            )
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            session.headers.update({"User-Agent": DEFAULT_UA})
            _session = session
        return _session


def close_session() -> None:
    """Release every pooled socket. Safe to call more than once."""
    global _session
    with _lock:
        if _session is not None:
            _session.close()
            _session = None


atexit.register(close_session)


def http_get_bytes(
    url: str,
    *,
    timeout: float = 20.0,
    headers: Mapping[str, str] | None = None,
    stream: bool = False,
) -> bytes:
    """GET ``url`` over the pooled session and return the body.

    ``stream=True`` is for large downloads (the SEC quarterly zips): the body is
    still returned whole, but it is read in chunks so a multi-megabyte response
    does not have to be materialised twice.
    """
    try:
        response = get_session().get(
            url, timeout=timeout, headers=dict(headers or {}), stream=stream
        )
        try:
            response.raise_for_status()
            if not stream:
                return response.content
            return b"".join(response.iter_content(chunk_size=1 << 16))
        finally:
            # Returns the socket to the pool (or closes it) even when the body
            # was only partly read — the case that leaked descriptors before.
            response.close()
    except requests.RequestException as exc:
        raise HttpFetchError(f"{url} -> {type(exc).__name__}: {exc}") from exc


def http_get_json(
    url: str,
    *,
    timeout: float = 20.0,
    headers: Mapping[str, str] | None = None,
) -> Any:
    """GET ``url`` and parse JSON, raising :class:`HttpFetchError` on any failure."""
    import json

    raw = http_get_bytes(url, timeout=timeout, headers=headers)
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise HttpFetchError(f"{url} -> invalid JSON: {exc}") from exc


def pool_stats() -> dict[str, int]:
    """How many connection pools and idle sockets the session is holding.

    Counts the proxy managers as well as the direct pool manager. On a machine
    with a system-wide proxy every request is routed through
    ``adapter.proxy_manager``, leaving ``adapter.poolmanager`` empty — so
    looking only at the latter reports zero while sockets are in fact open.
    """
    session = _session
    if session is None:
        return {"pools": 0, "idle_connections": 0}

    managers: list[Any] = []
    for adapter in session.adapters.values():
        direct = getattr(adapter, "poolmanager", None)
        if direct is not None:
            managers.append(direct)
        managers.extend(getattr(adapter, "proxy_manager", {}).values())

    pools = 0
    idle = 0
    seen: set[int] = set()
    for manager in managers:
        if id(manager) in seen:
            continue                       # one adapter is mounted for both schemes
        seen.add(id(manager))
        for pool in getattr(manager.pools, "_container", {}).values():
            pools += 1
            queue = getattr(pool, "pool", None)
            if queue is not None:
                idle += queue.qsize()
    return {"pools": pools, "idle_connections": idle}


__all__ = [
    "DEFAULT_UA",
    "HttpFetchError",
    "close_session",
    "get_session",
    "http_get_bytes",
    "http_get_json",
    "pool_stats",
]
