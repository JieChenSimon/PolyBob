from __future__ import annotations

import json

import pytest

from libs.data.http_client import HttpFetchError
from libs.data.resilient import FetchPolicy, fetch_cached_bytes, load_checkpoint, save_checkpoint


def test_fetch_cached_bytes_retries_then_writes_verified_cache(tmp_path):
    calls = 0

    def flaky(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise HttpFetchError("temporary")
        return b"real provider payload"

    result = fetch_cached_bytes(
        "https://example.test/immutable",
        cache_dir=tmp_path,
        policy=FetchPolicy(attempts=3, initial_backoff_seconds=0, max_backoff_seconds=0),
        fetcher=flaky,
    )
    assert result == b"real provider payload"
    assert calls == 3
    assert list(tmp_path.glob("*.body"))
    assert list(tmp_path.glob("*.json"))

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("cache should be used")

    assert fetch_cached_bytes(
        "https://example.test/immutable", cache_dir=tmp_path, fetcher=should_not_run
    ) == result


def test_fetch_cached_bytes_exhaustion_is_visible(tmp_path):
    def broken(*_args, **_kwargs):
        raise HttpFetchError("provider blocked")

    with pytest.raises(HttpFetchError, match="exhausted 2 attempts"):
        fetch_cached_bytes(
            "https://example.test/broken", cache_dir=tmp_path,
            policy=FetchPolicy(attempts=2, initial_backoff_seconds=0, max_backoff_seconds=0),
            fetcher=broken,
        )


def test_checkpoint_is_atomic_and_spec_scoped(tmp_path):
    path = tmp_path / "checkpoint.json"
    payload = {"spec": "v1", "items": {"a": "done"}}
    save_checkpoint(path, payload)
    assert json.loads(path.read_text()) == payload
    assert load_checkpoint(path, spec="v1") == payload
    assert load_checkpoint(path, spec="v2") == {"spec": "v2", "items": {}}
