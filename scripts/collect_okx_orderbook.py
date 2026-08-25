"""Collect real OKX public order-book snapshots into the local data lake.

Snapshots are live observations, not historical reconstruction. The resulting
dataset is useful for forward paper-trading validation, but promotion remains
blocked until the quote history covers the replay interval and every fill can
be linked to a snapshot with sufficient depth.
"""

from __future__ import annotations

import argparse
import json
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


def collect(symbols: list[str], *, levels: int = 20) -> dict[str, Any]:
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="BTC-USDT,ETH-USDT,SOL-USDT")
    parser.add_argument("--levels", type=int, default=20)
    args = parser.parse_args()
    result = collect([item.strip() for item in args.symbols.split(",") if item.strip()], levels=args.levels)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
