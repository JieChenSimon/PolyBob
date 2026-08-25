"""Collect real OKX public order-book snapshots into the local data lake.

Snapshots are live observations, not historical reconstruction. The resulting
dataset is useful for forward paper-trading validation, but promotion remains
blocked until the quote history covers the replay interval and every fill can
be linked to a snapshot with sufficient depth.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from typing import Any

from libs.data.data_lake import record_raw, write_records
from libs.data.http_client import HttpFetchError, http_get_bytes

API = "https://www.okx.com/api/v5/market/books"


def _positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def normalize_snapshot(symbol: str, payload: dict[str, Any], *, observed_at: datetime) -> dict[str, Any]:
    if payload.get("code") != "0" or not payload.get("data"):
        raise ValueError(f"OKX order book unavailable for {symbol}: {payload.get('msg')}")
    book = payload["data"][0]
    asks = book.get("asks") or []
    bids = book.get("bids") or []
    if not asks or not bids:
        raise ValueError(f"OKX order book has no two-sided levels for {symbol}")
    best_ask = _positive(asks[0][0])
    best_bid = _positive(bids[0][0])
    ask_depth = sum(_positive(level[1]) or 0.0 for level in asks)
    bid_depth = sum(_positive(level[1]) or 0.0 for level in bids)
    if best_ask is None or best_bid is None or best_ask <= best_bid:
        raise ValueError(f"OKX order book is invalid for {symbol}")
    quote_ts = int(book.get("ts") or int(observed_at.timestamp() * 1000))
    event_at = datetime.fromtimestamp(quote_ts / 1000.0, tz=UTC).isoformat()
    return {
        "symbol": symbol,
        "event_at": event_at,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "bid_depth": bid_depth,
        "ask_depth": ask_depth,
        "bid_levels": len(bids),
        "ask_levels": len(asks),
        "sequence_id": str(book.get("seqId") or "unknown"),
        "source": "okx_public_market_books",
        "quote_quality": "full_depth" if bid_depth > 0 and ask_depth > 0 else "missing_depth",
        "history_scope": "live_observation",
        "observed_at": observed_at.isoformat(),
    }


def _collect_once(symbols: list[str], *, levels: int = 20) -> dict[str, Any]:
    if not symbols:
        raise ValueError("at least one symbol is required")
    if not 1 <= levels <= 400:
        raise ValueError("levels must be between 1 and 400")
    observed_at = datetime.now(UTC)
    records = []
    raw = []
    for symbol in symbols:
        url = f"{API}?instId={symbol}&sz={levels}"
        try:
            payload_bytes = http_get_bytes(url, timeout=20.0, headers={"User-Agent": "PolyBob real-data research"})
        except HttpFetchError as exc:
            raise RuntimeError(f"OKX request failed for {symbol}: {exc}") from exc
        raw.append(record_raw("okx_orderbook_raw", payload_bytes, source="www.okx.com", request=url,
                              observed_at=observed_at))
        records.append(normalize_snapshot(symbol, json.loads(payload_bytes), observed_at=observed_at))
    stored = write_records("okx_orderbook", records, source="www.okx.com", observed_at=observed_at,
                           partition_by=("symbol",))
    return {
        "schema_version": "okx-orderbook-live-v1",
        "observed_at": observed_at.isoformat(),
        "history_scope": "live_observation",
        "symbols": symbols,
        "levels": levels,
        "records": len(records),
        "raw": raw,
        "normalized": stored,
        "promotion": "BLOCKED",
        "promotion_reason": "live_snapshots_do_not_prove_historical_execution_evidence",
    }


def collect_stream(symbols: list[str], *, levels: int = 20,
                   interval_seconds: float = 5.0, polls: int = 1,
                   checkpoint: str | None = None) -> dict[str, Any]:
    """Poll real OKX books into a forward, timestamped replay dataset.

    This creates a *new* history from real observations; it never backfills
    the past or relabels live snapshots as historical.  The bounded poll count
    and checkpoint make unattended collection restartable without an
    unbounded process or an unbounded log/file stream.
    """
    if interval_seconds < 0.5:
        raise ValueError("interval_seconds must be at least 0.5 seconds")
    if polls <= 0:
        raise ValueError("polls must be positive")
    checkpoint_path = None
    if checkpoint:
        from pathlib import Path
        checkpoint_path = Path(checkpoint)
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    results = []
    for poll in range(1, polls + 1):
        result = _collect_once(symbols, levels=levels)
        result["poll"] = poll
        result["polls"] = polls
        results.append(result)
        if checkpoint_path:
            checkpoint_path.write_text(json.dumps({
                "status": "running" if poll < polls else "completed",
                "poll": poll,
                "polls": polls,
                "symbols": symbols,
                "last_observed_at": result["observed_at"],
                "updated_at": datetime.now(UTC).isoformat(),
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if poll < polls:
            elapsed = time.monotonic() - started
            time.sleep(max(0.0, interval_seconds - (elapsed % interval_seconds)))
    return {
        "schema_version": "okx-orderbook-forward-replay-v1",
        "history_scope": "forward_real_observation",
        "symbols": symbols,
        "levels": levels,
        "polls": polls,
        "interval_seconds": interval_seconds,
        "snapshots": results,
        "promotion": "BLOCKED",
        "promotion_reason": "forward_live_observations_do_not_prove_prior_historical_execution",
    }


def collect(symbols: list[str], *, levels: int = 20) -> dict[str, Any]:
    """Collect one real live snapshot (backward-compatible entry point)."""
    return _collect_once(symbols, levels=levels)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="BTC-USDT,ETH-USDT,SOL-USDT")
    parser.add_argument("--levels", type=int, default=20)
    parser.add_argument("--polls", type=int, default=1,
                        help="bounded real polls; >1 builds forward history")
    parser.add_argument("--interval-seconds", type=float, default=5.0)
    parser.add_argument("--checkpoint", default=None)
    args = parser.parse_args()
    symbols = [item.strip() for item in args.symbols.split(",") if item.strip()]
    result = collect_stream(symbols, levels=args.levels,
                            interval_seconds=args.interval_seconds,
                            polls=args.polls, checkpoint=args.checkpoint)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
