"""Warm the EDGAR daily-filing cache so the US insider edge can be judged live.

The verdict path reads this cache and never fetches, because warming a cold
twenty-day window costs a few thousand requests and takes minutes — fine for a
scheduled job, unacceptable inside a page load. Run this once a day (after the
US close, when EDGAR has published the day's index):

    uv run --locked python scripts/warm_insider_cache.py

A past day's filings never change, so each day is fetched exactly once. The
first run fills the whole window; later runs fetch only the new day.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, date, datetime, timedelta

from libs.data.sec_daily_insider import (
    DailyInsiderUnavailable,
    _cache_path,
    scan_day,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=25,
                        help="trailing calendar days to cover (default 25 ≈ 20 sessions)")
    parser.add_argument("--as-of", type=str, default=None, help="YYYY-MM-DD")
    args = parser.parse_args()

    as_of = date.fromisoformat(args.as_of) if args.as_of else datetime.now(UTC).date()
    print("=" * 78)
    print(f"WARM EDGAR 每日申报缓存 — 截至 {as_of},回溯 {args.days} 天")
    print("=" * 78)

    total_events = 0
    fetched = skipped = failed = 0
    started = time.time()

    for offset in range(args.days + 1):
        day = as_of - timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        if _cache_path(day).exists():
            skipped += 1
            continue
        try:
            events = scan_day(day)
        except DailyInsiderUnavailable as exc:
            # Holidays land here too, and are indistinguishable from an outage
            # at this level — both are simply days without data.
            print(f"  {day}  跳过:{str(exc)[:70]}")
            failed += 1
            continue
        fetched += 1
        total_events += len(events)
        detail = ", ".join(f"{e.symbol}({e.insiders}人)" for e in events[:4])
        print(f"  {day}  集群 {len(events):2}  {detail}")

    elapsed = time.time() - started
    print(f"\n新抓取 {fetched} 天,已缓存跳过 {skipped} 天,无数据 {failed} 天;"
          f"新增集群事件 {total_events} 个,耗时 {elapsed:.0f}s")
    if fetched == 0 and skipped == 0:
        print("⚠️  一天都没读到 —— 检查网络或代理(SEC 需要能直连 www.sec.gov)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
