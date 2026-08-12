"""Rebuild the vendor response cache from scratch.

``data/market_cache/`` used to be committed — 613 files, 306MB, which made every
experiment re-run a 300MB diff and pinned the repository's history to whatever the
providers happened to return that day. It is a cache: derivable and replaceable.
This script is what makes that claim true, so it must stay runnable.

What is *not* a cache and stays in git: ``data/*_results.json`` (the per-event
returns the board verifies), ``data/promotion_board.json``,
``data/hypothesis_registry.json``. Those are evidence.

    uv run --locked python scripts/warm_cache.py            # everything
    uv run --locked python scripts/warm_cache.py --only us  # one domain

Providers are hit politely and sequentially. A failure is reported and skipped,
never substituted: a missing bar is missing, and the experiments already know how
to refuse rather than interpolate.
"""

from __future__ import annotations

import argparse
import time

from libs.data.real_sources import (
    DataUnavailable,
    fetch_a_share_daily,
    fetch_altcoin_daily,
    fetch_funding_rate_daily,
    fetch_us_equity_daily,
)
from libs.data.universe import (
    A_SHARE_LIQUID,
    US_BENCHMARK,
    US_INDEX_PROXIES,
    US_LIQUID,
    altcoin_pairs,
    altcoin_swaps,
)

PAUSE_SECONDS = 0.6


def _warm(label: str, items, fetch) -> tuple[int, int]:
    ok = failed = 0
    print(f"\n=== {label} ({len(items)}) ===")
    for item in items:
        try:
            fetch(item)
            ok += 1
            print(f"  ✓ {item}")
        except DataUnavailable as exc:
            failed += 1
            print(f"  ✗ {item}: {exc}")
        except Exception as exc:  # noqa: BLE001 — one bad symbol must not end the run
            failed += 1
            print(f"  ✗ {item}: {type(exc).__name__}: {exc}")
        time.sleep(PAUSE_SECONDS)
    return ok, failed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only", choices=["us", "a_share", "altcoin"], action="append",
        help="warm just one domain; repeatable. Default: all.",
    )
    args = parser.parse_args()
    wanted = set(args.only or ["us", "a_share", "altcoin"])

    totals = [0, 0]
    if "us" in wanted:
        # The benchmark first: without SPY no US event study can compute an excess
        # return at all, so a cold cache should fail on it immediately rather than
        # after four hundred symbol fetches.
        symbols = (US_BENCHMARK, *US_INDEX_PROXIES, *US_LIQUID)
        seen: list[str] = []
        for s in symbols:
            if s not in seen:
                seen.append(s)
        ok, bad = _warm("US equities", seen, lambda s: fetch_us_equity_daily(s, years=5))
        totals[0] += ok
        totals[1] += bad

    if "a_share" in wanted:
        ok, bad = _warm("A-shares", A_SHARE_LIQUID, lambda s: fetch_a_share_daily(s))
        totals[0] += ok
        totals[1] += bad

    if "altcoin" in wanted:
        ok, bad = _warm("Altcoin bars", altcoin_pairs(), lambda s: fetch_altcoin_daily(s))
        totals[0] += ok
        totals[1] += bad
        # Funding is not optional colour: the tradable leg is a perp short, and a
        # short's P&L includes funding. Missing funding means the short leg is not
        # measurable for that coin.
        ok, bad = _warm("Altcoin funding", altcoin_swaps(),
                        lambda s: fetch_funding_rate_daily(s.replace("-SWAP", "")))
        totals[0] += ok
        totals[1] += bad

    print(f"\n{'='*60}\n预热完成:{totals[0]} 成功,{totals[1]} 失败")
    if totals[1]:
        print("失败的标的没有被填充占位值——实验会照常拒绝它们,不会插值。")
    print("\nSEC 每日申报索引另有专门脚本(窗口冷启动要几千个请求):")
    print("  python scripts/warm_insider_cache.py")


if __name__ == "__main__":
    main()
