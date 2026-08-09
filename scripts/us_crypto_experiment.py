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
    fetch_funding_rate_daily,
    fetch_us_equity_daily,
)
from libs.data.universe import ALTCOIN_MAJORS, US_BENCHMARK, US_LIQUID
from libs.data import run_manifest
from libs.quant.hypothesis import Hypothesis, HypothesisRegistry, Rationale
from libs.quant import edge_backtest
from libs.quant.edge import Direction
from libs.quant.pbo import deflated_t_stat_threshold

# From libs/data/universe, not a literal. The universe is part of the hypothesis:
# "clustered insider selling is informative" is a different claim over twenty
# mega-caps than over five, and a list typed into a script cannot be compared with
# a list typed into another one.
US_UNIVERSE = list(US_LIQUID)
ALTS = list(ALTCOIN_MAJORS)
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
        # n_configs counts every reported group that could have been claimed as
        # the edge if it had come out significant — cluster and the single-seller
        # comparison here. Pre-registered controls are still trials: the search
        # that matters is the one over what you would have been willing to
        # believe, not the one you admit to afterwards.
        n_configs=2,
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
        # Crowded-long spot, crowded-long as a funded perp short, crowded-short.
        n_configs=3,
    ))


def funding_carry(rates_by_coin: dict[str, dict[str, float]]):
    """Build the ``carry`` callback the shared replay uses for a perp short.

    Funding is not colour on a perp short, it is part of its P&L. OKX settles every
    8h and :func:`fetch_funding_rate_daily` averages the three settlements per UTC
    day, so a day's total is ``3 × mean``. A positive rate means longs pay shorts —
    exactly the state this hypothesis selects on, so assuming zero where it is
    unmeasured would bias the one leg being traded.

    Returning ``None`` makes :func:`edge_backtest.replay_events` drop the event.
    That is the honest choice: without funding the short is not measurable, and a
    missing number must never become a zero.
    """
    def carry(symbol: str, signal_date: str, dates, entry_index: int) -> float | None:
        coin = symbol.split("-")[0]
        rates = rates_by_coin.get(coin)
        if not rates:
            return None
        window = list(dates[entry_index:entry_index + HOLD_DAYS])
        if len(window) < HOLD_DAYS:
            return None
        values = [rates.get(d) for d in window]
        if any(v is None for v in values):
            return None
        return float(sum(v * 3.0 for v in values))  # type: ignore[misc]

    return carry


def stats_block(
    name: str, events: list[tuple[str, str]], n_trials: int, as_of,
    *, direction: Direction, cost_bps: float, benchmark: str | None = None,
    carry=None,
) -> dict:
    """Price one group through the shared replay.

    This script used to hold its own ``forward_return``, as did the insider study,
    while the live scanner held none — so the board approved a strategy with an exit
    rule and the product surfaced a signal without one. The hold, the entry timing,
    the benchmark alignment and the cost now come from
    :mod:`libs.quant.edge_backtest`, which the live path reads too.

    The altcoin side is where the i.i.d. assumption failed hardest: eight majors
    that co-move, crowding at the same moment, held five days. 248 events live in 14
    distinct weeks, so ``sqrt(248)`` reported t=6.40 where the weekly cluster gives
    1.81 against a 4.19 hurdle. Same returns, wrong denominator.
    """
    result = edge_backtest.replay_events(
        events, direction=direction, hold_sessions=HOLD_DAYS,
        benchmark=benchmark, cost_bps=cost_bps, as_of=as_of,
        t_hurdle=deflated_t_stat_threshold(n_trials), edge_id=name, carry=carry,
    )
    if len(result.trades) < 100:
        return {"strategy": name, "n": len(result.trades),
                "note": "sample too small — not tested"}
    payload = result.to_dict()
    payload["strategy"] = name
    # The figure is a *position's* return now, not the instrument's excess, so the
    # leg has to say which side it is. Reading "-0.68%" without knowing it is a
    # short inverts the conclusion.
    payload["direction"] = direction.value
    payload["carry_included"] = carry is not None
    return payload


def _report(results: list[dict]) -> None:
    """Print both statistics, so the gap between them stays visible."""
    for r in results:
        if "mean_excess_pct" not in r:
            print(f"  {r['strategy']:24} n={r['n']:<5} {r.get('note','')}")
            continue
        side = {"long": "多", "short": "空", "avoid": "避"}.get(r.get("direction", ""), "?")
        print(f"  {r['strategy']:24} n={r['n']:<5} 独立单元={r['n_clusters']:<4} "
              f"[{side}]收益 {r['mean_excess_pct']:+.2f}% 胜率 {r['win_rate']*100:.1f}% "
              f"t(iid)={r['t_stat_iid']:+.2f} t(聚类/{r['cluster_by']})={r['t_stat']:+.2f} "
              f"(门槛 {r['t_hurdle']}) {'✅' if r['significant'] else '❌'}")
        for warning in r.get("warnings", []):
            print(f"    ⚠ {warning}")


def run_us(registry: HypothesisRegistry, as_of) -> list[dict]:
    print("\n=== 美股:内部人卖出集群 ===")
    try:
        fetch_us_equity_daily(US_BENCHMARK)      # warms the store
    except DataUnavailable as exc:
        print(f"  基准不可用: {exc}")
        return []

    # Collect *signals*, not returns. Pricing belongs to the shared replay so this
    # study and the live scanner cannot drift apart on what the trade actually is.
    clusters: list[tuple[str, str]] = []
    singles: list[tuple[str, str]] = []
    for symbol in US_UNIVERSE:
        try:
            events = fetch_insider_transactions(symbol)
            fetch_us_equity_daily(symbol)        # warms the store
        except (SignalDataUnavailable, DataUnavailable):
            continue
        by_date: dict[str, int] = defaultdict(int)
        for e in events:
            if e.is_open_market_sell and e.filing_date:
                by_date[e.filing_date] += 1
        for date, count in by_date.items():
            (clusters if count >= 3 else singles).append((symbol, date))
        time.sleep(1.05)      # respect the provider's rate limit

    n = registry.n_trials
    # The pre-registered direction is short_or_avoid, so the sell-cluster leg is
    # priced as a short. Testing it long would be reversing a falsified hypothesis.
    results = [
        stats_block("内部人卖出集群(≥3人同日)", sorted(clusters), n, as_of,
                    direction=Direction.SHORT, cost_bps=US_COST_BPS,
                    benchmark=US_BENCHMARK),
        stats_block("对照:单人卖出", sorted(singles), n, as_of,
                    direction=Direction.SHORT, cost_bps=US_COST_BPS,
                    benchmark=US_BENCHMARK),
    ]
    _report(results)
    return results


def run_altcoins(registry: HypothesisRegistry, as_of) -> list[dict]:
    print("\n=== 山寨币:散户拥挤度 ===")
    crowded_long: list[tuple[str, str]] = []
    crowded_short: list[tuple[str, str]] = []
    funding_by_coin: dict[str, dict[str, float]] = {}

    for ccy in ALTS:
        try:
            positioning = fetch_retail_positioning(ccy)
            fetch_altcoin_daily(f"{ccy}-USDT")        # warms the store
        except (SignalDataUnavailable, DataUnavailable):
            continue
        try:
            funding_by_coin[ccy] = fetch_funding_rate_daily(f"{ccy}-USDT")
        except DataUnavailable:
            # No funding history means the short leg is not measurable for this
            # coin. The replay will drop those events rather than assume zero.
            pass

        ratios = [p.long_short_ratio for p in positioning]
        for i, point in enumerate(positioning):
            if i < 30:                     # trailing window keeps the rule causal
                continue
            window = np.asarray(ratios[max(0, i - 30):i], dtype=float)
            hi, lo = np.percentile(window, 80), np.percentile(window, 20)
            if point.long_short_ratio > hi:
                crowded_long.append((f"{ccy}-USDT", point.date))
            elif point.long_short_ratio < lo:
                crowded_short.append((f"{ccy}-USDT", point.date))

    n = registry.n_trials
    results = [
        # The spot leg: does price fall after retail crowds long? No funding, because
        # nothing is being financed — this is the mechanism check, not the trade.
        stats_block("散户极度做多后(预期跌)", sorted(crowded_long), n, as_of,
                    direction=Direction.LONG, cost_bps=ALT_COST_BPS),
        # The tradable leg: a funded perp short. Funding is part of its P&L and
        # unmeasured funding drops the event rather than becoming zero.
        stats_block("散户极度做多后 做空(含资金费)", sorted(crowded_long), n, as_of,
                    direction=Direction.SHORT, cost_bps=ALT_COST_BPS,
                    carry=funding_carry(funding_by_coin)),
        stats_block("散户极度做空后(预期涨)", sorted(crowded_short), n, as_of,
                    direction=Direction.LONG, cost_bps=ALT_COST_BPS),
    ]
    _report(results)
    return results


def main() -> None:
    print("=" * 84)
    print("PRE-REGISTERED — US equities + altcoins (real data, beyond price)")
    print("=" * 84)
    registry = HypothesisRegistry()
    preregister(registry)
    manifest = run_manifest.pin("altcoin_retail_crowding", params={"hold_days": HOLD_DAYS, "us_cost_bps": US_COST_BPS, "alt_cost_bps": ALT_COST_BPS,
        "us_universe": US_UNIVERSE, "alts": ALTS, "percentile_window": 30})
    print(f"观测时点 as_of = {manifest.as_of.isoformat()}")
    print(f"预注册 2 个假设;累计试验 {registry.n_trials}")

    us_results = run_us(registry, manifest.as_of)
    alt_results = run_altcoins(registry, manifest.as_of)
    results = us_results + alt_results
    out = Path("data/us_crypto_results.json")
    out.write_text(json.dumps({
        "generated_at": datetime.now(UTC).isoformat(), "real_data_only": True,
        "hold_days": HOLD_DAYS, "n_trials": registry.n_trials,
        "us_cost_bps": US_COST_BPS, "alt_cost_bps": ALT_COST_BPS,
        "inference": "cluster_robust",   # the board refuses rows without this
        "results": results,
    }, indent=2, ensure_ascii=False))

    # Record the verdict against the hypothesis that predicted it. Leaving these
    # blank is how the registry ended up holding pre-registrations with no
    # results while a hand-written board claimed those same edges as evidence.
    #
    # The recorded row must be the leg the hypothesis named. ``altcoin_retail_crowding``
    # says ``short_when_retail_crowded_long``, and the board trades
    # ``short_perp_when_retail_crowded_long`` — so the funded short leg is the
    # result, not the spot leg that happens to be listed first. Recording the
    # wrong index left the registry and the board citing different numbers for
    # the same edge.
    def _verdict(row: dict) -> dict:
        return {k: v for k, v in row.items() if k != "events"}

    if us_results:
        registry.record_result("insider_sell_cluster", _verdict(us_results[0]))
    short_leg = next(
        (r for r in alt_results if r["strategy"] == "散户极度做多后 做空(含资金费)"), None
    )
    if short_leg is not None:
        registry.record_result("altcoin_retail_crowding", _verdict(short_leg))
    manifest.record_input("us_insiders", universe=len(US_UNIVERSE))
    manifest.record_input("altcoin_positioning", coins=len(ALTS))
    written = manifest.save(out)

    hits = sum(1 for r in results if r.get("significant"))
    print(f"\n{hits}/{len(results)} 组显著。写入 {out}")
    print(f"运行清单 {written}")
    for warning in manifest.warn_lines():
        print(f"  ⚠ {warning}")


if __name__ == "__main__":
    main()
