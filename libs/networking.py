"""Shared outbound-network configuration and diagnostics."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
import platform
import re
import subprocess
from urllib.parse import urlsplit, urlunsplit

import httpx


@dataclass(frozen=True)
class NetworkFailure:
    category: str
    retryable: bool
    detail: str


def read_macos_https_proxy() -> dict[str, object]:
    """Read the active macOS HTTPS proxy without exposing credentials."""
    if platform.system() != "Darwin":
        return {"enabled": False, "host": "", "port": 0}

    try:
        result = subprocess.run(
            ["scutil", "--proxy"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"enabled": False, "host": "", "port": 0}

    enabled = re.search(r"HTTPSEnable\s*:\s*1", result.stdout) is not None
    host_match = re.search(r"HTTPSProxy\s*:\s*([^\s]+)", result.stdout)
    port_match = re.search(r"HTTPSPort\s*:\s*(\d+)", result.stdout)
    return {
        "enabled": enabled,
        "host": host_match.group(1) if host_match else "",
        "port": int(port_match.group(1)) if port_match else 0,
    }


def resolve_outbound_proxy(
    *,
    env: Mapping[str, str] | None = None,
    platform_name: str | None = None,
    macos_proxy: Mapping[str, object] | None = None,
) -> str | None:
    """Resolve an explicit proxy first, then the active macOS HTTPS proxy."""
    values = os.environ if env is None else env
    explicit = (
        values.get("POLYBOB_OUTBOUND_PROXY")
        or values.get("HTTPS_PROXY")
        or values.get("ALL_PROXY")
    )
    if explicit:
        return explicit

    system = platform.system() if platform_name is None else platform_name
    if system != "Darwin":
        return None

    proxy = read_macos_https_proxy() if macos_proxy is None else macos_proxy
    if proxy.get("enabled") and proxy.get("host") and proxy.get("port"):
        return f"http://{proxy['host']}:{proxy['port']}"
    return None


def redact_proxy_url(value: str | None) -> str | None:
    """Remove user information from a proxy URL before logging or returning it."""
    if value is None:
        return None

    parsed = urlsplit(value)
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = f"{host}:{parsed.port}" if parsed.port else host
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def classify_network_error(error: Exception) -> NetworkFailure:
    """Convert transport exceptions into stable, user-visible failure categories."""
    if isinstance(error, httpx.ConnectTimeout):
        return NetworkFailure("connect_timeout", True, str(error))
    if isinstance(error, httpx.ReadTimeout):
        return NetworkFailure("read_timeout", True, str(error))
    if isinstance(error, httpx.ProxyError):
        return NetworkFailure("proxy_error", True, str(error))
    if isinstance(error, httpx.ConnectError):
        return NetworkFailure("connect_error", True, str(error))
    if isinstance(error, httpx.HTTPStatusError):
        status_code = error.response.status_code
        return NetworkFailure(
            f"http_{status_code}",
            status_code in {418, 429} or status_code >= 500,
            str(error),
        )
    return NetworkFailure("unexpected", False, str(error))
