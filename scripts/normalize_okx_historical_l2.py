"""Reconstruct and sample a real OKX historical L2 snapshot/update archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tarfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from libs.data.data_lake import MANIFEST, read_manifest


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _apply(book: dict[float, float], levels: list[list[Any]]) -> None:
    for level in levels:
        if not level:
            continue
        price = _number(level[0])
        size = _number(level[1]) if len(level) > 1 else 0.0
        if price <= 0:
            continue
        if size <= 0:
            book.pop(price, None)
        else:
            book[price] = size


def _sample(symbol: str, ts_ms: int, bids: dict[float, float], asks: dict[float, float],
            *, interval_ms: int, raw_sha256: str, updates: int) -> dict[str, Any] | None:
    if not bids or not asks:
        return None
    bid_prices = sorted(bids, reverse=True)[:20]
    ask_prices = sorted(asks)[:20]
    return {
        "symbol": symbol,
        "event_at": datetime.fromtimestamp(ts_ms / 1000.0, tz=UTC).isoformat(),
        "event_ts_ms": ts_ms,
        "best_bid": bid_prices[0],
        "best_ask": ask_prices[0],
        "bid_depth_top20": sum(bids[p] for p in bid_prices),
        "ask_depth_top20": sum(asks[p] for p in ask_prices),
        "bid_levels_top20": len(bid_prices),
        "ask_levels_top20": len(ask_prices),
        "quote_quality": "sampled_full_depth",
        "history_scope": "historical_orderbook_sampled",
        "sampling_interval_ms": interval_ms,
        "raw_archive_sha256": raw_sha256,
        "updates_applied": updates,
        "source": "www.okx.com_historical_l2",
    }


def normalize_archive(archive: Path, output: Path, *, interval_ms: int = 1000,
                      cpu_target: float = 0.45) -> dict[str, Any]:
    if interval_ms <= 0:
        raise ValueError("interval_ms must be positive")
    digest = hashlib.sha256()
    with archive.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    raw_sha256 = digest.hexdigest()
    bids: dict[float, float] = {}
    asks: dict[float, float] = {}
    rows: list[dict[str, Any]] = []
    first_ts = last_ts = None
    next_sample = None
    line_count = snapshot_count = update_count = invalid_count = 0
    last_wall = time.monotonic()
    last_cpu = time.process_time()
    output.parent.mkdir(parents=True, exist_ok=True)
    pending = output.with_name(f".{output.name}.pending")
    writer = None
    try:
        with tarfile.open(archive, "r|gz") as bundle:
            member = bundle.next()
            if member is None:
                raise ValueError("archive has no member")
            stream = bundle.extractfile(member)
            if stream is None:
                raise ValueError("archive member is not readable")
            for raw_line in stream:
                line_count += 1
                try:
                    item = json.loads(raw_line)
                    ts_ms = int(item["ts"])
                    action = str(item["action"])
                    if action == "snapshot":
                        bids.clear(); asks.clear(); snapshot_count += 1
                    elif action == "update":
                        update_count += 1
                    else:
                        invalid_count += 1
                        continue
                    _apply(asks, item.get("asks") or [])
                    _apply(bids, item.get("bids") or [])
                    first_ts = ts_ms if first_ts is None else min(first_ts, ts_ms)
                    last_ts = ts_ms if last_ts is None else max(last_ts, ts_ms)
                    if next_sample is None:
                        next_sample = ts_ms
                    if ts_ms >= next_sample:
                        row = _sample(str(item.get("instId") or "unknown"), ts_ms, bids, asks,
                                      interval_ms=interval_ms, raw_sha256=raw_sha256,
                                      updates=update_count)
                        if row is not None:
                            rows.append(row)
                        while next_sample <= ts_ms:
                            next_sample += interval_ms
                except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                    invalid_count += 1
                # Check frequently enough that a busy update burst cannot
                # keep the process above the workstation CPU budget for a
                # long interval.  The parser is intentionally I/O-bound and
                # can trade wall time for safe resource use.
                if line_count % 10_000 == 0:
                    wall = time.monotonic() - last_wall
                    cpu = time.process_time() - last_cpu
                    if wall > 0 and cpu / wall > cpu_target:
                        time.sleep(min(cpu / cpu_target - wall, 2.0))
                    last_wall = time.monotonic(); last_cpu = time.process_time()
        if not rows:
            raise ValueError("archive produced no two-sided samples")
        table = pa.Table.from_pylist(rows)
        pq.write_table(table, pending, compression="zstd")
        pending.replace(output)
    finally:
        pending.unlink(missing_ok=True)
    manifest_entry = {
        "kind": "normalized",
        "dataset": "okx_historical_orderbook_sampled_1s",
        "source": "www.okx.com_historical_l2",
        "path": str(output),
        "raw_archive_sha256": raw_sha256,
        "rows": len(rows),
        "event_start": datetime.fromtimestamp(first_ts / 1000, tz=UTC).isoformat() if first_ts else None,
        "event_end": datetime.fromtimestamp(last_ts / 1000, tz=UTC).isoformat() if last_ts else None,
        "history_scope": "historical_orderbook_sampled",
        "sampling_interval_ms": interval_ms,
        "line_count": line_count,
        "snapshot_count": snapshot_count,
        "update_count": update_count,
        "invalid_count": invalid_count,
        "normalized_at": datetime.now(UTC).isoformat(),
    }
    existing = {str(item.get("path")) for item in read_manifest() if item.get("kind") == "normalized"}
    if str(output) not in existing:
        with MANIFEST.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(manifest_entry, ensure_ascii=False, sort_keys=True) + "\n")
    return {"schema_version": "okx-historical-l2-sampled-v1", "real_data_only": True,
            "output": str(output), **manifest_entry}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--interval-ms", type=int, default=1000)
    args = parser.parse_args()
    print(json.dumps(normalize_archive(args.archive, args.output, interval_ms=args.interval_ms),
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
