"""Safely materialize a bounded batch of UNKNOWN equity candidates.

This is deliberately a low-rate, resumable pre-warm step.  It never treats a
provider error as a usable instrument and never starts one request per roster
member unless the caller explicitly schedules repeated batches.  Successful
fetches are mirrored by ``libs.data.real_sources`` into the bitemporal daily-bar
store; the checkpoint records only the fetch outcome and can be replayed.

Example::

    uv run --locked python scripts/warm_equity_universe.py \
      --manifest data/discovered_equity_universe_full.json \
      --domain us_equity --max-symbols 25
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from libs.data.real_sources import (
    DataUnavailable,
    fetch_a_share_daily,
    fetch_us_equity_daily,
)
from libs.data.resilient import load_checkpoint, save_checkpoint

DEFAULT_CHECKPOINT = Path("data/equity_universe_warm_checkpoint.json")
CHECKPOINT_SPEC = "equity-universe-warm-v1"


def _unknown_candidates(manifest: dict[str, Any], domain: str) -> list[dict[str, Any]]:
    """Return deterministic UNKNOWN rows that still need local history."""
    rows = [
        row for row in manifest.get("candidates", [])
        if row.get("domain") == domain
        and row.get("status") == "UNKNOWN"
        and "no_local_daily_bars" in (row.get("reasons") or [])
    ]
    return sorted(rows, key=lambda row: str(row.get("symbol", "")))


def _fetcher(domain: str) -> Callable[[str], Any]:
    if domain == "us_equity":
        return lambda symbol: fetch_us_equity_daily(symbol, years=5)
    if domain == "a_share":
        return lambda symbol: fetch_a_share_daily(symbol, days=1200)
    raise ValueError(f"unsupported domain: {domain}")


def warm_batch(
    manifest: dict[str, Any],
    *,
    domain: str,
    max_symbols: int,
    checkpoint_path: str | Path = DEFAULT_CHECKPOINT,
    min_interval_seconds: float = 1.0,
    attempts: int = 2,
    retry_backoff_seconds: float = 2.0,
    budget_seconds: float = 900.0,
    fetch: Callable[[str], Any] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Warm at most ``max_symbols`` with bounded time and durable progress."""
    if max_symbols < 1:
        raise ValueError("max_symbols must be positive")
    if attempts < 1:
        raise ValueError("attempts must be positive")
    if min_interval_seconds < 0 or budget_seconds <= 0:
        raise ValueError("interval must be non-negative and budget must be positive")

    checkpoint = load_checkpoint(checkpoint_path, spec=CHECKPOINT_SPEC)
    items = checkpoint.setdefault("items", {})
    candidates = _unknown_candidates(manifest, domain)
    selected: list[dict[str, Any]] = []
    for row in candidates:
        symbol = str(row["symbol"])
        prior = items.get(f"{domain}:{symbol}")
        if prior and prior.get("status") == "READY_FETCHED":
            continue
        selected.append(row)
        if len(selected) >= max_symbols:
            break

    fetch = fetch or _fetcher(domain)
    started = clock()
    last_request_at: float | None = None
    results: list[dict[str, Any]] = []

    for row in selected:
        symbol = str(row["symbol"])
        if clock() - started >= budget_seconds:
            break
        if last_request_at is not None:
            wait = min_interval_seconds - (clock() - last_request_at)
            if wait > 0:
                sleep(wait)
        last_request_at = clock()
        outcome: dict[str, Any] = {
            "domain": domain,
            "symbol": symbol,
            "started_at": datetime.now(UTC).isoformat(),
            "attempts": 0,
        }
        error: Exception | None = None
        for attempt in range(1, attempts + 1):
            outcome["attempts"] = attempt
            try:
                bars = fetch(symbol)
                if not getattr(bars, "is_usable", False):
                    raise DataUnavailable(f"{symbol}: fetched history is shorter than 200 bars")
                outcome.update({
                    "status": "READY_FETCHED",
                    "bars": len(bars),
                    "latest": bars.dates[-1] if bars.dates else None,
                    "price_basis": bars.price_basis,
                    "finished_at": datetime.now(UTC).isoformat(),
                })
                error = None
                break
            except Exception as exc:  # preserve provider-specific failure in evidence
                error = exc
                if attempt < attempts:
                    sleep(retry_backoff_seconds * attempt)
        if error is not None:
            outcome.update({
                "status": "UNKNOWN_FETCH_FAILED",
                "error": f"{type(error).__name__}: {error}",
                "finished_at": datetime.now(UTC).isoformat(),
            })
        items[f"{domain}:{symbol}"] = outcome
        save_checkpoint(checkpoint_path, checkpoint)
        results.append(outcome)

    return {
        "spec": CHECKPOINT_SPEC,
        "domain": domain,
        "selected": len(selected),
        "processed": len(results),
        "ready_fetched": sum(item["status"] == "READY_FETCHED" for item in results),
        "failed": sum(item["status"] == "UNKNOWN_FETCH_FAILED" for item in results),
        "checkpoint": str(checkpoint_path),
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("data/discovered_equity_universe_full.json"))
    parser.add_argument("--domain", required=True, choices=("us_equity", "a_share"))
    parser.add_argument("--max-symbols", type=int, default=25)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--min-interval-seconds", type=float, default=1.0)
    parser.add_argument("--attempts", type=int, default=2)
    parser.add_argument("--retry-backoff-seconds", type=float, default=2.0)
    parser.add_argument("--budget-seconds", type=float, default=900.0)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    result = warm_batch(
        manifest,
        domain=args.domain,
        max_symbols=args.max_symbols,
        checkpoint_path=args.checkpoint,
        min_interval_seconds=args.min_interval_seconds,
        attempts=args.attempts,
        retry_backoff_seconds=args.retry_backoff_seconds,
        budget_seconds=args.budget_seconds,
    )
    print(json.dumps({key: value for key, value in result.items() if key != "results"}, ensure_ascii=False))
    for item in result["results"]:
        print(json.dumps(item, ensure_ascii=False))


if __name__ == "__main__":
    main()
