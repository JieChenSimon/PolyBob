import httpx

from libs.networking import classify_network_error, redact_proxy_url, resolve_outbound_proxy


def test_explicit_polybob_proxy_wins():
    proxy = resolve_outbound_proxy(
        env={
            "POLYBOB_OUTBOUND_PROXY": "http://127.0.0.1:7892",
            "HTTPS_PROXY": "http://fallback:8080",
        },
        platform_name="Darwin",
        macos_proxy={"enabled": True, "host": "127.0.0.1", "port": 9999},
    )

    assert proxy == "http://127.0.0.1:7892"


def test_https_proxy_precedes_macos_proxy():
    proxy = resolve_outbound_proxy(
        env={"HTTPS_PROXY": "http://environment:8080"},
        platform_name="Darwin",
        macos_proxy={"enabled": True, "host": "127.0.0.1", "port": 7892},
    )

    assert proxy == "http://environment:8080"


def test_macos_proxy_is_used_when_environment_is_empty():
    proxy = resolve_outbound_proxy(
        env={},
        platform_name="Darwin",
        macos_proxy={"enabled": True, "host": "127.0.0.1", "port": 7892},
    )

    assert proxy == "http://127.0.0.1:7892"


def test_disabled_macos_proxy_does_not_create_a_proxy_url():
    proxy = resolve_outbound_proxy(
        env={},
        platform_name="Darwin",
        macos_proxy={"enabled": False, "host": "127.0.0.1", "port": 7892},
    )

    assert proxy is None


def test_proxy_credentials_are_redacted():
    assert (
        redact_proxy_url("http://user:secret@proxy.example:8080")
        == "http://proxy.example:8080"
    )


def test_connect_timeout_is_classified_as_retryable():
    failure = classify_network_error(httpx.ConnectTimeout("connect timed out"))

    assert failure.category == "connect_timeout"
    assert failure.retryable is True


def test_rate_limit_is_classified_as_retryable():
    request = httpx.Request("GET", "https://example.com")
    response = httpx.Response(429, request=request)
    failure = classify_network_error(
        httpx.HTTPStatusError("rate limited", request=request, response=response)
    )

    assert failure.category == "http_429"
    assert failure.retryable is True
