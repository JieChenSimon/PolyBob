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

Inference: **clustered by month**, not i.i.d. The holding period is 20 sessions,
so two clusters filing a week apart share most of one price path — they are not
two independent observations. This script used to divide by ``sqrt(n)`` with
n=753 and report t=5.40; the honest denominator uses the ~9 independent months
the sample actually spans, which gives t=2.29. See
:mod:`libs.quant.clustered_inference`. The per-event returns and dates are now
written to the result file so the board can verify this rather than trust it.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from libs.data.real_sources import DataUnavailable, fetch_us_equity_daily
from libs.data.sec_insider import SecDataUnavailable, cluster_buys, fetch_insider_trades
from libs.data import run_manifest
from libs.data.universe import US_BENCHMARK
from libs.quant import edge_backtest
from libs.quant.edge import Direction
from libs.quant.hypothesis import Hypothesis, HypothesisRegistry, Rationale
from libs.quant.pbo import deflated_t_stat_threshold

QUARTERS = [(2025, 3), (2025, 4), (2026, 1)]
HOLD_DAYS = 20          # insider signals are documented over weeks, not days
COST_BPS = 10.0
# No symbol cap. There used to be ``MAX_SYMBOLS = 260``, filled with the tickers
# carrying the *most* events — and that is a selection on the treatment variable.
# It excluded 353 of 1,141 clusters, and every single excluded stock had exactly one
# event while the included ones averaged 3.03. So the study's real population was
# "stocks where insiders cluster-buy **repeatedly**", which is a narrower and
# self-selected claim than the hypothesis states.
#
# The cap existed to bound Yahoo calls. The bitemporal store removes that reason:
# prices are read from ``libs/data/store`` rather than fetched per run, so the
# universe can be every stock that carries an event.


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


def summarise(
    name: str, events: list[tuple[str, str]], n_trials: int, as_of,
    universe: list[str] | None = None,
) -> dict:
    """Price one group through the shared replay and return its evidence.

    ``events`` is (symbol, filing_date) — the *signals*. This script no longer owns
    an exit rule. It used to hold its own ``forward_return``, and so did
    ``us_crypto_experiment``, and the live scanner held none at all: the board
    approved a 20-session hold measured against SPY net of costs while the product
    surfaced a signal with no exit. Those were different objects and only one of
    them had a t-statistic.

    The hold, the benchmark, the entry timing and the cost now come from
    :mod:`libs.quant.edge_backtest`, which the live path reads too. Prices come from
    the bitemporal store at ``as_of``, so the sample is fixed and reproducible
    rather than being whatever the providers last returned.
    """
    result = edge_backtest.replay_events(
        events,
        direction=Direction.LONG,
        hold_sessions=HOLD_DAYS,
        benchmark=US_BENCHMARK,
        cost_bps=COST_BPS,
        as_of=as_of,
        t_hurdle=deflated_t_stat_threshold(n_trials),
        edge_id=name,
        # Cross-sectional control rather than SPY. Insider clusters concentrate in
        # small caps and SPY is large-cap, so a SPY-excess return carries a size-factor
        # exposure inside what gets called alpha. Chosen on that prior ground, not
        # because it flattered the result — it gives a *lower* t (3.58 vs 3.67), which
        # is the honest direction: part of the old figure was beta.
        neutralise_universe=universe,
    )
    if len(result.trades) < 100:
        return {"strategy": name, "n": len(result.trades),
                "note": "sample too small — not tested"}
    payload = result.to_dict()
    payload["strategy"] = name
    return payload


def main() -> None:
    print("=" * 86)
    print("PRE-REGISTERED — insider cluster buying (full SEC Form 345 data)")
    print("=" * 86)
    registry = HypothesisRegistry()
    preregister(registry)
    print(f"累计试验 {registry.n_trials}")

    # Pin the observation cut before the first read. Everything this run sees is
    # what was known at this instant — which is the only reason its n will be the
    # same next time. It was not: this experiment reported 753 events one day and
    # 667 the next, off the same overwritable cache.
    manifest = run_manifest.pin("insider_cluster_buy", params={
        "quarters": QUARTERS, "hold_days": HOLD_DAYS,
        "cost_bps": COST_BPS, "symbol_cap": None,
        "benchmark_mode": "cross_sectional_universe_mean",
        "min_insiders": 2, "min_value_usd": 50_000,
        "benchmark": US_BENCHMARK,
    })
    print(f"观测时点 as_of = {manifest.as_of.isoformat()}\n")

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

    # Every stock that carries an event — no frequency ranking, no cap.
    symbols = sorted({symbol for symbol, _ in list(clusters) + list(singles)})
    print(f"事件涉及 {len(symbols)} 只股票,全部纳入(不再按事件频次筛选)")

    prices: dict[str, tuple[list[str], list[float]]] = {}
    missing: list[str] = []
    for symbol in symbols:
        try:
            bars = fetch_us_equity_daily(symbol, years=2)
            prices[symbol] = (bars.dates, bars.closes)
        except DataUnavailable:
            missing.append(symbol)
            continue
    print(f"  取到 {len(prices)} 只,{len(missing)} 只无价格")
    if missing:
        # Coverage is a selection warning, not a footnote. If the unpriceable names
        # are systematically the illiquid ones, that selection sits inside the
        # result — and the previous version reported no such number at all.
        print(f"  ⚠ 覆盖率 {len(prices)/len(symbols)*100:.1f}% —— "
              f"取不到价格的标的若系统性偏向流动性差的小盘股,这个偏差会留在结果里")

    try:
        fetch_us_equity_daily(US_BENCHMARK, years=2)      # warms the store
    except DataUnavailable as exc:
        print(f"基准不可用: {exc}")
        return

    # Every fetch above mirrored into the bitemporal store, so the replay reads
    # prices *as they were known at* the manifest's cut rather than as they look
    # now. Restated, backfilled and survivorship-cleaned history is what makes a
    # backtest describe a strategy nobody could have run.
    n = registry.n_trials
    results = [
        summarise("内部人集群买入(≥2人)", sorted(clusters), n, manifest.as_of, symbols),
        summarise("对照:单人买入", sorted(singles), n, manifest.as_of, symbols),
    ]
    for row in results:
        if row.get("dropped"):
            print(f"  {row['strategy']}: 信号 {row['signals_found']},可定价 {row['n']} "
                  f"(覆盖 {row['measurable_rate']*100:.1f}%),丢弃 {row['dropped']}")

    # Both t-statistics are printed side by side. The i.i.d. column is kept
    # visible precisely because it is the wrong one: seeing 5.40 next to 2.29 is
    # what makes the size of the error legible.
    print(f"\n{'组':22} {'n':>6} {'独立单元':>8} {'平均超额':>9} {'中位':>8} "
          f"{'胜率':>7} {'t(iid)':>8} {'t(聚类)':>8} {'门槛':>6}  显著?")
    for r in results:
        if "mean_excess_pct" not in r:
            print(f"{r['strategy']:22} {r['n']:>6}  {r['note']}")
            continue
        print(f"{r['strategy']:22} {r['n']:>6} {r['n_clusters']:>8} "
              f"{r['mean_excess_pct']:>8.2f}% {r['median_excess_pct']:>7.2f}% "
              f"{r['win_rate']*100:>6.1f}% {r['t_stat_iid']:>8.2f} {r['t_stat']:>8.2f} "
              f"{r['t_hurdle']:>6.2f}  {'✅' if r['significant'] else '❌'}")
        for warning in r.get("warnings", []):
            print(f"{'':22} ⚠ {warning}")

    manifest.record_input("insider_filings", quarters=len(QUARTERS), trades=len(trades),
                          clusters=len(clusters), singles=len(singles))
    manifest.record_input("daily_bars", symbols_requested=len(symbols),
                          symbols_available=len(prices),
                          price_coverage=round(len(prices) / max(1, len(symbols)), 4))

    out = Path("data/insider_results.json")
    out.write_text(json.dumps({
        "generated_at": datetime.now(UTC).isoformat(), "real_data_only": True,
        "source": "SEC Form 345", "quarters": QUARTERS, "hold_days": HOLD_DAYS,
        "n_trials": n, "cost_bps": COST_BPS,
        "inference": "cluster_robust",   # the board refuses rows without this
        "results": results,
    }, indent=2, ensure_ascii=False))
    # The registry keeps the verdict, not the raw events — and it keeps the
    # *comparison*, because the hypothesis is not "insider buying predicts returns"
    # but "**clustered** buying carries the strongest signal". Recording only the
    # treatment group hides whether that second clause survived.
    def _verdict(row: dict) -> dict:
        return {k: v for k, v in row.items() if k != "events"}

    cluster, control = _verdict(results[0]), _verdict(results[1])
    payload = dict(cluster)
    payload["control_single_buy"] = control

    # Once the frequency-based symbol cap was removed, the control's clustered
    # t-statistic came out *above* the treatment's (3.04 vs 2.72 on the first such
    # run). Neither clears the hurdle, so nothing was promoted either way — but the
    # clustering premise is not supported by this sample, and the old cap had been
    # flattering it by over-weighting stocks with repeat clusters.
    both = [c.get("t_stat") for c in (cluster, control)]
    if all(t is not None for t in both) and abs(both[1]) >= abs(both[0]):
        payload["clustering_premise"] = "unsupported_control_at_least_as_strong"
        print(f"\n⚠ 对照组(单人买入)的聚类 t = {both[1]:+.2f},不低于集群组的 {both[0]:+.2f}。"
              f"\n  '集群比单人更强' 这一条没有得到本样本支持 —— 两组都没过门槛,"
              f"\n  但这说明去掉按事件频次筛股之后,集群假设失去了它原有的优势。")
    registry.record_result("insider_cluster_buy", payload)
    written = manifest.save(out)
    print(f"\n写入 {out}")
    print(f"运行清单 {written}")
    for warning in manifest.warn_lines():
        print(f"  ⚠ {warning}")


if __name__ == "__main__":
    main()
