"""Regression tests for the pooled HTTP layer.

The bug these protect against was found on the operator's own machine: a
long-running API process held 15 sockets in ``CLOSED`` against 5 live ones after
19 hours, because every provider call opened a fresh connection via
``urllib.request.urlopen`` and the descriptor was never released. With a
system-wide proxy in front, each of those became a tunnel connection the OS then
had to keep alive during sleep — which is what turned a laptop in a bag into a
machine waking every seven seconds.

These tests use a local HTTP server, so they need no network and no provider.
"""

from __future__ import annotations

import http.server
import os
import subprocess
import threading

import pytest

from libs.data import http_client


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - stdlib naming
        # ``/notjson`` mimics a provider that answers 200 with an error page —
        # the case that must raise rather than parse into an empty result.
        if self.path.startswith("/notjson"):
            body, content_type = b"<html>rate limited</html>", "text/html"
        else:
            body, content_type = b'{"ok": true}', "application/json"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802 - stdlib naming
        size = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(size)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep the test output clean
        return


@pytest.fixture()
def local_server():
    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # A proxy configured for the real machine must not intercept the fixture.
    saved = {k: os.environ.pop(k, None)
             for k in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy")}
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    http_client.close_session()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/"
    finally:
        server.shutdown()
        http_client.close_session()
        for key, value in saved.items():
            if value is not None:
                os.environ[key] = value


def _open_sockets() -> int:
    result = subprocess.run(
        ["lsof", "-nP", "-a", "-p", str(os.getpid()), "-i"],
        capture_output=True, text=True, check=False,
    )
    return len([line for line in result.stdout.splitlines()[1:] if line.strip()])


def test_repeated_requests_do_not_leak_sockets(local_server):
    """20 requests must not hold 20 sockets — the connection has to be reused."""
    http_client.http_get_bytes(local_server, timeout=5)
    baseline = _open_sockets()

    for _ in range(20):
        http_client.http_get_bytes(local_server, timeout=5)

    after = _open_sockets()
    # One or two extra descriptors is normal churn; growth proportional to the
    # request count is the leak.
    assert after - baseline <= 2, (
        f"socket count grew from {baseline} to {after} over 20 requests — "
        "connections are not being reused"
    )


def test_pool_is_bounded(local_server):
    """The pool must stay small: idle sockets are what the OS wakes to service."""
    for _ in range(20):
        http_client.http_get_bytes(local_server, timeout=5)

    stats = http_client.pool_stats()
    assert stats["idle_connections"] <= http_client.POOL_MAXSIZE, stats


def test_close_session_releases_everything(local_server):
    """Shutdown must actually drop the sockets, not just forget about them."""
    http_client.http_get_bytes(local_server, timeout=5)
    assert http_client.pool_stats()["pools"] >= 1

    http_client.close_session()
    assert http_client.pool_stats() == {"pools": 0, "idle_connections": 0}


def test_failure_is_raised_not_swallowed(local_server):
    """An unreachable provider must surface, never return empty bytes."""
    with pytest.raises(http_client.HttpFetchError):
        http_client.http_get_bytes("http://127.0.0.1:1/nope", timeout=2)


def test_json_parse_failure_is_explicit(local_server):
    """A body that is not JSON is a provider failure, not an empty dict."""
    with pytest.raises(http_client.HttpFetchError):
        http_client.http_get_json(local_server + "notjson", timeout=5)


def test_post_json_uses_shared_session(local_server):
    payload = http_client.http_post_json(local_server + "echo", {"ok": True}, timeout=5)
    assert payload["ok"] is True
