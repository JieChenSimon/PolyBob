from __future__ import annotations

from pathlib import Path

from scripts.warm_equity_universe import warm_batch


class _Bars:
    is_usable = True
    price_basis = "test_real_source"
    dates = ["2026-08-20", "2026-08-21"]

    def __len__(self):
        return 200


def _manifest(*symbols: str) -> dict:
    return {
        "candidates": [
            {"domain": "us_equity", "symbol": symbol, "status": "UNKNOWN",
             "reasons": ["no_local_daily_bars"]}
            for symbol in symbols
        ]
    }


def test_warm_batch_is_bounded_resumable_and_skips_ready(tmp_path: Path):
    calls: list[str] = []

    def fetch(symbol: str):
        calls.append(symbol)
        return _Bars()

    checkpoint = tmp_path / "warm.json"
    first = warm_batch(
        _manifest("AAA", "BBB", "CCC"), domain="us_equity", max_symbols=2,
        checkpoint_path=checkpoint, min_interval_seconds=0, fetch=fetch,
    )
    assert first["processed"] == 2
    assert calls == ["AAA", "BBB"]

    second = warm_batch(
        _manifest("AAA", "BBB", "CCC"), domain="us_equity", max_symbols=2,
        checkpoint_path=checkpoint, min_interval_seconds=0, fetch=fetch,
    )
    assert second["processed"] == 1
    assert calls == ["AAA", "BBB", "CCC"]


def test_warm_batch_preserves_provider_failure_as_unknown(tmp_path: Path):
    def broken(_symbol: str):
        raise RuntimeError("provider limited")

    result = warm_batch(
        _manifest("AAA"), domain="us_equity", max_symbols=1,
        checkpoint_path=tmp_path / "warm.json", min_interval_seconds=0,
        attempts=2, retry_backoff_seconds=0, fetch=broken,
    )
    assert result["failed"] == 1
    assert result["results"][0]["status"] == "UNKNOWN_FETCH_FAILED"
    assert result["results"][0]["attempts"] == 2
