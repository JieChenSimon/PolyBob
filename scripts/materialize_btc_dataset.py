"""Rebuild normalized BTC 1-minute bars from immutable cached OKX responses."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq
from libs.data.data_lake import read_manifest, write_records

DATASET = "btc_1m_bars_clean_v2"


def main() -> None:
    records: list[dict[str, object]] = []
    seen: set[int] = set()
    for entry in read_manifest():
        request = entry.get("request") or ""
        if entry.get("dataset") != "btc5m_provider_raw" or "okx.com/api/v5/market/history-candles" not in request:
            continue
        payload = json.loads(open(entry["path"], "rb").read())
        for row in payload.get("data", []):
            timestamp = int(row[0])
            if timestamp < 1_577_836_800_000:  # 2020-01-01; reject corrupt epoch rows
                continue
            if timestamp in seen:
                continue
            seen.add(timestamp)
            records.append({
                "symbol": "BTC-USDT",
                "event_at": datetime.fromtimestamp(timestamp / 1000, tz=UTC).isoformat(),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
                "source": "okx_history_candles",
            })
    # Include any previously materialized clean bars, then canonicalize by
    # market timestamp.  A provider can return the same minute with a revised
    # payload; keeping one deterministic row prevents downstream replay from
    # counting that minute twice.  The old dataset is never deleted.
    legacy_root = Path("data/datasets/parts/btc_1m_bars_clean")
    for path in legacy_root.rglob("*.parquet"):
        for row in pq.read_table(path).to_pylist():
            timestamp = int(datetime.fromisoformat(str(row["event_at"]).replace("Z", "+00:00")).timestamp() * 1000)
            if timestamp not in seen:
                seen.add(timestamp)
                records.append(row)
    records.sort(key=lambda item: str(item["event_at"]))
    result = write_records(DATASET, records, source="okx_history_candles", partition_by=("symbol",))
    print(f"materialized {DATASET}: {result.get('rows', 0):,} unique rows")


if __name__ == "__main__":
    main()
