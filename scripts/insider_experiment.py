"""Pre-registered test of the insider-buying anomaly on full SEC data.

Previously untestable: the vendor feed held only 23 open-market purchases across
a year of mega-caps. The SEC's own Form 345 datasets carry ~5,700 purchases per
quarter across 4,000+ tickers, which finally makes the anomaly measurable —
especially in the small and mid caps where insiders actually buy.

Hypothesis (registered before results are inspected): a *cluster* of insider
purchases — several insiders filing on the same day — predicts positive excess
returns. Mechanism: insiders know their own business, an open-market purchase
costs them real money and is legally constrained, so clustered buying is
expensive to fake and unlikely to be coincident liquidity need. Single purchases
are the weaker control.

Timing: entry uses ``FILING_DATE`` (public disclosure), never the trade date.
Returns are excess of SPY over the same window and net of costs.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from libs.data.real_sources import DataUnavailable, fetch_us_equity_daily
from libs.data.sec_insider import SecDataUnavailable, cluster_buys, fetch_insider_trades
from libs.quant.hypothesis import Hypothesis, HypothesisRegistry, Rationale
from libs.quant.pbo import deflated_t_stat_threshold

QUARTERS = [(2025, 3), (2025, 4), (2026, 1)]
HOLD_DAYS = 20          # insider signals are documented over weeks, not days
COST_BPS = 10.0
MAX_SYMBOLS = 260       # cap Yahoo calls; symbols chosen by event frequency


def preregister(registry: HypothesisRegistry) -> None:
    registry.register(Hypothesis(
        hypothesis_id="insider_cluster_buy",
        claim="Stocks where several insiders buy on the open market outperform over the next month.",
        rationale=Rationale.BEHAVIOURAL,
        mechanism=("Insiders hold private information about their own firm; an open-market "
                   "purchase costs real money and is legally constrained, so clustered "
                   "buying is expensive to fake. The market underreacts to the filing."),
        literature=("Insider purchases predict returns while sales are largely "
                    "diversification noise; clustered trades carry the strongest signal."),
        direction="long_after_cluster_buy_filing",
        universe="All US issuers in SEC Form 345",
        horizon_days=HOLD_DAYS, cost_bps=COST_BPS,
    ))


def forward_return(dates: list[str], closes: list[float], date: str, hold: int) -> float | None:
    """Enter at the first close on/after the filing date; exit ``hold`` sessions later."""
    idx = next((i for i, d in enumerate(dates) if d >= date), None)
    if idx is None or idx + hold >= len(closes) or closes[idx] <= 0:
        return None
    return closes[idx + hold] / closes[idx] - 1.0


def summarise(name: str, rets: list[float], n_trials: int) -> dict:
    arr = np.asarray([r for r in rets if np.isfinite(r)], dtype=float)
    if len(arr) < 100:
        return {"strategy": name, "n": int(len(arr)), "note": "sample too small — not tested"}
    sd = arr.std(ddof=1)
    t = float(arr.mean() / (sd / np.sqrt(len(arr)))) if sd > 0 else 0.0
    hurdle = deflated_t_stat_threshold(n_trials)
    return {
        "strategy": name, "n": int(len(arr)),
        "mean_excess_pct": round(float(arr.mean()) * 100, 3),
        "median_excess_pct": round(float(np.median(arr)) * 100, 3),
        "win_rate": round(float((arr > 0).mean()), 4),
        "t_stat": round(t, 2), "t_hurdle": round(hurdle, 2),
        "significant": bool(abs(t) >= hurdle),
    }


def main() -> None:
    print("=" * 86)
    print("PRE-REGISTERED — insider cluster buying (full SEC Form 345 data)")
    print("=" * 86)
    registry = HypothesisRegistry()
    preregister(registry)
    print(f"累计试验 {registry.n_trials}\n")

    trades = []
    for year, quarter in QUARTERS:
        try:
            batch = fetch_insider_trades(year, quarter)
            trades.extend(batch)
            print(f"  {year}Q{quarter}: {len(batch)} 笔")
        except SecDataUnavailable as exc:
            print(f"  ! {year}Q{quarter}: {exc}")
    if not trades:
        print("无 SEC 数据,终止")
        return

    clusters = cluster_buys(trades, min_insiders=2)
    singles: dict[tuple[str, str], float] = defaultdict(float)
    for t in trades:
        if t.is_open_market_buy and t.value_usd >= 50_000:
            singles[(t.symbol, t.filing_date)] += t.value_usd
    singles = {k: v for k, v in singles.items() if k not in clusters}
    print(f"\n集群买入事件 {len(clusters)}, 单人买入事件 {len(singles)}")

    # Fetch prices only for the symbols that actually carry events.
    counts: dict[str, int] = defaultdict(int)
    for symbol, _ in list(clusters) + list(singles):
        counts[symbol] += 1
    symbols = [s for s, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:MAX_SYMBOLS]]
    print(f"取事件最多的 {len(symbols)} 只股票的真实价格…")

    prices: dict[str, tuple[list[str], list[float]]] = {}
    for symbol in symbols:
        try:
            bars = fetch_us_equity_daily(symbol, years=2)
            prices[symbol] = (bars.dates, bars.closes)
        except DataUnavailable:
            continue
    print(f"  取到 {len(prices)} 只")

    try:
        spy = fetch_us_equity_daily("SPY", years=2)
    except DataUnavailable as exc:
        print(f"基准不可用: {exc}")
        return
    bench = {d: forward_return(spy.dates, spy.closes, d, HOLD_DAYS) for d in spy.dates}

    def collect(events) -> list[float]:
        out: list[float] = []
        for symbol, date in events:
            data = prices.get(symbol)
            if not data:
                continue
            r = forward_return(data[0], data[1], date, HOLD_DAYS)
            b = bench.get(date)
            if b is None:                       # filing on a non-trading day
                b = next((bench[d] for d in spy.dates if d >= date and bench.get(d) is not None), None)
            if r is None or b is None:
                continue
            out.append(r - b - COST_BPS / 1e4)
        return out

    cluster_rets = collect(clusters)
    single_rets = collect(singles)
    n = registry.n_trials
    results = [
        summarise("内部人集群买入(≥2人)", cluster_rets, n),
        summarise("对照:单人买入", single_rets, n),
    ]

    print(f"\n{'组':22} {'n':>6} {'平均超额':>9} {'中位':>8} {'胜率':>7} {'t':>7} {'门槛':>6}  显著?")
    for r in results:
        if "mean_excess_pct" not in r:
            print(f"{r['strategy']:22} {r['n']:>6}  {r['note']}")
            continue
        print(f"{r['strategy']:22} {r['n']:>6} {r['mean_excess_pct']:>8.2f}% "
              f"{r['median_excess_pct']:>7.2f}% {r['win_rate']*100:>6.1f}% "
              f"{r['t_stat']:>7.2f} {r['t_hurdle']:>6.2f}  {'✅' if r['significant'] else '❌'}")

    out = Path("data/insider_results.json")
    out.write_text(json.dumps({
        "generated_at": datetime.now(UTC).isoformat(), "real_data_only": True,
        "source": "SEC Form 345", "quarters": QUARTERS, "hold_days": HOLD_DAYS,
        "results": results,
    }, indent=2, ensure_ascii=False))
    registry.record_result("insider_cluster_buy", results[0])
    print(f"\n写入 {out}")


if __name__ == "__main__":
    main()
