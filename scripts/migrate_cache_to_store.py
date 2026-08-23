"""Move the legacy JSON cache into the bitemporal store.

``data/market_cache/`` holds 613 raw provider responses with no observation time.
That is the defect, so the migration cannot invent one: the only honest stamp
available is the file's **modification time**, which is when we actually wrote it.
It is approximate (a file re-fetched five times keeps only the last mtime), and
every migrated row is marked ``source_migrated`` so a later reader can tell
"observed at this instant" from "we can only say it was on disk by then".

From here on, fetches go through the store and carry a real ``fetched_at``.
History before this migration is best-effort; history after it is exact.

    uv run --locked python scripts/migrate_cache_to_store.py --dry-run
    uv run --locked python scripts/migrate_cache_to_store.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path

from libs.data import store
from libs.data import data_lake

CACHE_DIR = Path("data/market_cache")


def _unwrap(payload):
    """Legacy cache files wrap the provider response under "rows"."""
    if isinstance(payload, dict):
        for key in ("rows", "data"):
            if isinstance(payload.get(key), list):
                return payload[key]
        return None
    return payload


def _mtime(path: Path) -> dt.datetime:
    return dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.UTC)


def _yahoo(path: Path) -> tuple[str, list[dict]] | None:
    """yahoo_<SYMBOL>_<years>.json — the chart API's nested envelope."""
    m = re.match(r"yahoo_(.+?)_\d+\.json$", path.name)
    if not m:
        return None
    payload = json.loads(path.read_text())
    result = ((payload.get("chart") or {}).get("result") or [None])[0]
    if not result:
        return None
    stamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    rows = []
    for i, ts in enumerate(stamps):
        def at(key: str):
            seq = quote.get(key) or []
            return seq[i] if i < len(seq) else None

        close = at("close")
        if close is None:
            continue          # a session with no close is not a bar
        rows.append({
            "symbol": m.group(1),
            store.EVENT_DATE: dt.datetime.fromtimestamp(ts, tz=dt.UTC).date().isoformat(),
            "open": at("open"), "high": at("high"), "low": at("low"),
            "close": close, "volume": at("volume"),
            "source": "yahoo_migrated",
        })
    return m.group(1), rows


def _okx_bars(path: Path) -> tuple[str, list[dict]] | None:
    """okx_<INST>_<n>.json — OKX candles: [ts, o, h, l, c, vol, ...]."""
    m = re.match(r"okx_(?!funding_)(.+?)_\d+\.json$", path.name)
    if not m:
        return None
    payload = json.loads(path.read_text())
    # The legacy cache wraps provider payloads under "rows"; older files were
    # written bare. Accept both rather than silently migrating nothing.
    candles = _unwrap(payload)
    if not isinstance(candles, list):
        return None
    rows = []
    for c in candles:
        if not isinstance(c, list) or len(c) < 6:
            continue
        rows.append({
            "symbol": m.group(1),
            store.EVENT_DATE: dt.datetime.fromtimestamp(
                int(c[0]) / 1000, tz=dt.UTC
            ).date().isoformat(),
            "open": float(c[1]), "high": float(c[2]), "low": float(c[3]),
            "close": float(c[4]), "volume": float(c[5]),
            "source": "okx_migrated",
        })
    return m.group(1), rows


def _okx_funding(path: Path) -> tuple[str, list[dict]] | None:
    m = re.match(r"okx_funding_(.+?)_\d+\.json$", path.name)
    if not m:
        return None
    payload = json.loads(path.read_text())
    items = _unwrap(payload)
    if not isinstance(items, list):
        return None
    by_day: dict[str, list[float]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        ts, rate = item.get("fundingTime"), item.get("realizedRate") or item.get("fundingRate")
        if ts is None or rate is None:
            continue
        day = dt.datetime.fromtimestamp(int(ts) / 1000, tz=dt.UTC).date().isoformat()
        by_day.setdefault(day, []).append(float(rate))
    rows = [
        {"symbol": m.group(1), store.EVENT_DATE: day,
         "rate": sum(v) / len(v), "source": "okx_migrated"}
        for day, v in by_day.items()
    ]
    return m.group(1), rows


def _tencent(path: Path) -> tuple[str, list[dict]] | None:
    """tencent_<sh|sz><code>_<n>.json — A-share daily."""
    m = re.match(r"tencent_(s[hz]\d+)_\d+\.json$", path.name)
    if not m:
        return None
    payload = json.loads(path.read_text())
    code = m.group(1)
    node = (payload.get("data") or {}).get(code) or {}
    series = node.get("qfqday") or node.get("day") or []
    rows = []
    for row in series:
        if not isinstance(row, list) or len(row) < 5:
            continue
        try:
            rows.append({
                "symbol": code[2:],
                store.EVENT_DATE: str(row[0])[:10],
                "open": float(row[1]), "close": float(row[2]),
                "high": float(row[3]), "low": float(row[4]),
                "volume": float(row[5]) if len(row) > 5 else None,
                "source": "tencent_migrated",
            })
        except (TypeError, ValueError):
            continue
    return code[2:], rows


def _positioning(path: Path) -> tuple[str, list[dict]] | None:
    m = re.match(r"positioning_(.+?)_\d+\.json$", path.name)
    if not m:
        return None
    payload = json.loads(path.read_text())
    # Positioning carries two series; the long/short account ratio is the one the
    # hypothesis is about. ``oi`` is open interest and belongs to a different claim.
    items = payload.get("ratio") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return None
    rows = []
    for item in items:
        if isinstance(item, list) and len(item) >= 2:
            ts, ratio = item[0], item[1]
        elif isinstance(item, dict):
            ts = item.get("ts") or item.get("timestamp")
            ratio = item.get("longShortRatio") or item.get("ratio")
        else:
            continue
        if ts is None or ratio is None:
            continue
        rows.append({
            "symbol": m.group(1),
            store.EVENT_DATE: dt.datetime.fromtimestamp(
                int(ts) / 1000, tz=dt.UTC
            ).date().isoformat(),
            "long_short_ratio": float(ratio), "source": "okx_migrated",
        })
    return m.group(1), rows


PARSERS = (
    (store.DAILY_BARS, _yahoo),
    (store.DAILY_BARS, _okx_bars),
    (store.DAILY_BARS, _tencent),
    (store.FUNDING_RATES, _okx_funding),
    (store.POSITIONING, _positioning),
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="only N files (for a smoke test)")
    args = parser.parse_args()

    files = sorted(CACHE_DIR.glob("*.json")) if CACHE_DIR.exists() else []
    if args.limit:
        files = files[: args.limit]
    print(f"扫描 {len(files)} 个缓存文件\n")

    migrated = skipped = rows_total = 0
    per_dataset: dict[str, int] = {}
    for path in files:
        if not args.dry_run:
            # Preserve the original provider response before normalizing it.
            # The file mtime is the only honest historical observation time
            # available for this legacy cache.
            data_lake.record_raw(
                "legacy_market_cache", path.read_bytes(),
                source="legacy_cache", request=str(path), observed_at=_mtime(path),
            )
        parsed = None
        ds = None
        for candidate_ds, fn in PARSERS:
            try:
                parsed = fn(path)
            except Exception as exc:  # noqa: BLE001 — a bad file is reported, not fatal
                print(f"  ! {path.name}: {type(exc).__name__}: {exc}")
                parsed = None
            if parsed:
                ds = candidate_ds
                break
        if not parsed or not ds or not parsed[1]:
            skipped += 1
            continue
        symbol, rows = parsed
        if not args.dry_run:
            store.write(
                ds, symbol, rows, fetched_at=_mtime(path),
                deduplicate_payload=True,
            )
        migrated += 1
        rows_total += len(rows)
        per_dataset[ds.name] = per_dataset.get(ds.name, 0) + len(rows)

    print(f"\n{'='*64}")
    print(f"{'(演练) ' if args.dry_run else ''}迁移 {migrated} 个文件,{rows_total:,} 行;跳过 {skipped}")
    for name, count in sorted(per_dataset.items()):
        print(f"  {name}: {count:,} 行")
    print("\n跳过的多是非行情缓存(insider_*/vix/fng/universe 等),它们由各自的抓取路径直接写入 store。")
    if not args.dry_run:
        print("\n=== store 覆盖情况 ===")
        for ds in store.DATASETS:
            c = store.coverage(ds)
            if c["rows"]:
                print(f"  {c['dataset']:16} {c['symbols']:>4} 标的 {c['rows']:>8,} 行  "
                      f"{c['start']}..{c['end']}")


if __name__ == "__main__":
    main()
