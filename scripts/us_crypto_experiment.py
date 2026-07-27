"""Pre-registered experiments for the other two domains: US equities + altcoins.

The A-share result came from information beyond price. These are the equivalent
tests for the remaining in-scope domains, held to the same standard: register
the mechanism first, use only real data, benchmark against the market, charge
costs, and clear a raised t-hurdle.

**US — insider selling clusters.** Insider *buying* is the strong signal in the
literature, but it is not testable here: across 20 large caps over the available
year there are only 23 open-market purchases, because mega-cap insiders sell
(RSU/option liquidation) and rarely buy. Under the real-data rule we do not run
an underpowered test and call it a result; instead we test the sell side, whose
weaker but real claim is that *clustered* selling — several insiders filing
within days — is informative, while isolated sales are diversification noise.

**Altcoins — retail crowding.** OKX publishes the long/short *account* ratio, a
direct read on retail positioning. Levered retail crowded on one side is fuel
for a squeeze, so extremes should revert. Percentiles are computed on a trailing
window so the rule stays causal.

Timing: insider events use ``filingDate`` (public disclosure), never
``transactionDate``.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from libs.data.flow_signals import (
    SignalDataUnavailable,
    fetch_insider_transactions,
    fetch_retail_positioning,
)
from libs.data.real_sources import (
    DataUnavailable,
    fetch_altcoin_daily,
    fetch_us_equity_daily,
)
from libs.quant.hypothesis import Hypothesis, HypothesisRegistry, Rationale
from libs.quant.pbo import deflated_t_stat_threshold

US_UNIVERSE = ["AAPL", "MSFT", "JPM", "XOM", "BAC", "WFC", "PFE", "T", "F", "INTC",
               "KO", "CVX", "GM", "C", "MRK", "VZ", "DIS", "NKE", "BA", "GE"]
ALTS = ["SOL", "DOGE", "ADA", "AVAX", "LINK", "LTC", "XRP", "BCH"]
HOLD_DAYS = 5
US_COST_BPS = 5.0
ALT_COST_BPS = 10.0


def preregister(registry: HypothesisRegistry) -> None:
    registry.register(Hypothesis(
        hypothesis_id="insider_sell_cluster",
        claim="Stocks where several insiders file open-market sales within days underperform.",
        rationale=Rationale.BEHAVIOURAL,
        mechanism=("A single insider sale is diversification noise, but several insiders "
                   "selling together is costly to fake and plausibly reflects shared "
                   "private information the market has not priced."),
        literature=("Insider trading is informative; clustered trades are the subset with "
                    "the strongest documented predictive content."),
        direction="short_or_avoid_after_cluster",
        universe="US large caps", horizon_days=HOLD_DAYS, cost_bps=US_COST_BPS,
    ))
    registry.register(Hypothesis(
        hypothesis_id="altcoin_retail_crowding",
        claim="Altcoins where retail accounts are extremely long underperform over the next week.",
        rationale=Rationale.STRUCTURAL,
        mechanism=("Retail perp accounts are levered; crowding on one side creates forced "
                   "liquidations on adverse moves, so extremes revert."),
        literature=("Crowded positioning and funding extremes precede squeezes in perps."),
        direction="short_when_retail_crowded_long",
        universe="OKX altcoin perps", horizon_days=HOLD_DAYS, cost_bps=ALT_COST_BPS,
    ))


def forward_return(dates: list[str], closes: list[float], date: str, hold: int) -> float | None:
    """Return from the close on/after ``date`` to ``hold`` sessions later."""
    idx = next((i for i, d in enumerate(dates) if d >= date), None)
    if idx is None or idx + hold >= len(closes) or closes[idx] <= 0:
        return None
    return closes[idx + hold] / closes[idx] - 1.0


def stats_block(name: str, rets: list[float], n_trials: int) -> dict:
    arr = np.asarray([r for r in rets if np.isfinite(r)], dtype=float)
    if len(arr) < 100:
        return {"strategy": name, "n": len(arr), "note": "sample too small — not tested"}
    sd = arr.std(ddof=1)
    t = float(arr.mean() / (sd / np.sqrt(len(arr)))) if sd > 0 else 0.0
    hurdle = deflated_t_stat_threshold(n_trials)
    return {
        "strategy": name, "n": len(arr),
        "mean_excess_pct": round(float(arr.mean()) * 100, 3),
        "median_excess_pct": round(float(np.median(arr)) * 100, 3),
        "win_rate": round(float((arr > 0).mean()), 4),
        "t_stat": round(t, 2), "t_hurdle": round(hurdle, 2),
        "significant": bool(abs(t) >= hurdle),
    }


def run_us(registry: HypothesisRegistry) -> list[dict]:
    print("\n=== 美股:内部人卖出集群 ===")
    try:
        spy = fetch_us_equity_daily("SPY")
    except DataUnavailable as exc:
        print(f"  基准不可用: {exc}")
        return []
    bench = {d: forward_return(spy.dates, spy.closes, d, HOLD_DAYS) for d in spy.dates}

    cluster_rets: list[float] = []
    single_rets: list[float] = []
    for symbol in US_UNIVERSE:
        try:
            events = fetch_insider_transactions(symbol)
            bars = fetch_us_equity_daily(symbol)
        except (SignalDataUnavailable, DataUnavailable):
            continue
        by_date: dict[str, int] = defaultdict(int)
        for e in events:
            if e.is_open_market_sell and e.filing_date:
                by_date[e.filing_date] += 1
        for date, count in by_date.items():
            r = forward_return(bars.dates, bars.closes, date, HOLD_DAYS)
            b = bench.get(date)
            if r is None or b is None:
                continue
            excess = r - b - US_COST_BPS / 1e4
            (cluster_rets if count >= 3 else single_rets).append(excess)
        time.sleep(1.05)      # respect the provider's rate limit

    n = registry.n_trials
    results = [
        stats_block("内部人卖出集群(≥3人同日)", cluster_rets, n),
        stats_block("对照:单人卖出", single_rets, n),
    ]
    for r in results:
        print("  " + (f"{r['strategy']:24} n={r['n']:<5} {r.get('note','')}" if "mean_excess_pct" not in r
                      else f"{r['strategy']:24} n={r['n']:<5} 超额 {r['mean_excess_pct']:+.2f}% "
                           f"胜率 {r['win_rate']*100:.1f}% t={r['t_stat']:+.2f} "
                           f"(门槛 {r['t_hurdle']}) {'✅' if r['significant'] else '❌'}"))
    return results


def run_altcoins(registry: HypothesisRegistry) -> list[dict]:
    print("\n=== 山寨币:散户拥挤度 ===")
    crowded_long: list[float] = []
    crowded_short: list[float] = []
    for ccy in ALTS:
        try:
            positioning = fetch_retail_positioning(ccy)
            bars = fetch_altcoin_daily(f"{ccy}-USDT")
        except (SignalDataUnavailable, DataUnavailable):
            continue
        ratios = [p.long_short_ratio for p in positioning]
        for i, point in enumerate(positioning):
            if i < 30:                     # trailing window keeps the rule causal
                continue
            window = np.asarray(ratios[max(0, i - 30):i], dtype=float)
            hi, lo = np.percentile(window, 80), np.percentile(window, 20)
            r = forward_return(bars.dates, bars.closes, point.date, HOLD_DAYS)
            if r is None:
                continue
            net = r - ALT_COST_BPS / 1e4
            if point.long_short_ratio > hi:
                crowded_long.append(net)
            elif point.long_short_ratio < lo:
                crowded_short.append(net)

    n = registry.n_trials
    results = [
        stats_block("散户极度做多后(预期跌)", crowded_long, n),
        stats_block("散户极度做空后(预期涨)", crowded_short, n),
    ]
    for r in results:
        print("  " + (f"{r['strategy']:24} n={r['n']:<5} {r.get('note','')}" if "mean_excess_pct" not in r
                      else f"{r['strategy']:24} n={r['n']:<5} 收益 {r['mean_excess_pct']:+.2f}% "
                           f"胜率 {r['win_rate']*100:.1f}% t={r['t_stat']:+.2f} "
                           f"(门槛 {r['t_hurdle']}) {'✅' if r['significant'] else '❌'}"))
    return results


def main() -> None:
    print("=" * 84)
    print("PRE-REGISTERED — US equities + altcoins (real data, beyond price)")
    print("=" * 84)
    registry = HypothesisRegistry()
    preregister(registry)
    print(f"预注册 2 个假设;累计试验 {registry.n_trials}")

    results = run_us(registry) + run_altcoins(registry)
    out = Path("data/us_crypto_results.json")
    out.write_text(json.dumps({
        "generated_at": datetime.now(UTC).isoformat(), "real_data_only": True,
        "hold_days": HOLD_DAYS, "results": results,
    }, indent=2, ensure_ascii=False))
    hits = sum(1 for r in results if r.get("significant"))
    print(f"\n{hits}/{len(results)} 组显著。写入 {out}")


if __name__ == "__main__":
    main()
