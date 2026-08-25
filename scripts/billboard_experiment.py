"""Pre-registered experiment: does A-share dragon-tiger flow predict returns?

Two competing, theory-driven hypotheses — registered before the results are
looked at, and both reported whatever they show:

- **H1 attention overreaction.** Publication of the list is an attention shock in
  a retail-dominated market; retail chasing pushes price past fair value and it
  reverts. Predicts NEGATIVE drift after listing.
- **H2 informed institutional flow.** When institution-only seats are net buyers,
  the disclosure reveals informed demand. Predicts POSITIVE (or materially less
  negative) drift for that subset.

They make opposite predictions on the institutional subset, so the data can
falsify at least one — that is the point of stating them in advance rather than
mining subsets until one looks good.

Discipline applied throughout:
- Entry at the D1 close (list publishes after the event close), exit at D5 —
  the overnight gap that cannot be traded is excluded.
- Excess return is measured against the CSI 300 over the same horizon, so a
  market-wide drift is never mistaken for alpha.
- Deflated Sharpe + PBO/CSCV + a t-hurdle above the factor-zoo standard.
- Implementability is checked explicitly: A-shares are hard to short, so a
  negative-drift result is reported as an avoidance filter, not a tradable short.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from libs.data.a_share_flow import BillboardEvent, capturable_return, fetch_billboard_events
from libs.data import run_manifest
from libs.data.http_client import http_get_json
from libs.quant.hypothesis import Hypothesis, HypothesisRegistry, Rationale
from libs.quant import clustered_inference
from libs.quant.pbo import deflated_t_stat_threshold, probability_of_backtest_overfitting

HOLD_DAYS = 5          # enter at D1 close, exit at D5 close
COST_BPS = 30.0        # A-share round trip: commission + stamp duty + slippage
MAX_EVENTS = 50_000    # the provider's full history; the sample size is evidence
BENCH_DAYS = 1400      # CSI 300 closes must span the oldest event, or it drops out


def preregister(registry: HypothesisRegistry) -> None:
    registry.register(Hypothesis(
        hypothesis_id="billboard_attention_reversal",
        claim=("Stocks published on the dragon-tiger list underperform over the "
               "following week."),
        rationale=Rationale.BEHAVIOURAL,
        mechanism=("The after-close disclosure is an attention shock; retail buying "
                   "pushes price beyond fair value. It is not arbitraged away because "
                   "A-shares have T+1 settlement, daily price limits and costly shorting."),
        literature=("Attention-driven retail overreaction and short-horizon reversal are "
                    "documented in retail-dominated markets."),
        direction="short_or_avoid_listed_names",
        universe="A-share dragon-tiger listings",
        horizon_days=HOLD_DAYS, cost_bps=COST_BPS,
    ))
    registry.register(Hypothesis(
        hypothesis_id="billboard_institutional_flow",
        claim=("Listings where institutional seats are net buyers outperform listings "
               "where they are not."),
        rationale=Rationale.STRUCTURAL,
        mechanism=("The exchange reveals seat-level flow; institution-only seats proxy "
                   "informed demand that the wider market has not yet priced."),
        literature=("Informed-flow disclosure predicts returns where the disclosure is "
                    "mandatory and seat-level."),
        direction="long_institutional_buy_listings",
        universe="A-share dragon-tiger listings",
        horizon_days=HOLD_DAYS, cost_bps=COST_BPS,
    ))


def csi300_horizon_returns() -> dict[str, float]:
    """Real CSI 300 closes -> {date: forward HOLD_DAYS return} for benchmarking."""
    url = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
           f"?param=sh000300,day,,,{BENCH_DAYS},qfq")
    payload = http_get_json(url, timeout=25.0, headers={"User-Agent": "Mozilla/5.0"})
    node = payload["data"]["sh000300"]
    rows = node.get("qfqday") or node.get("day") or []
    dates = [r[0] for r in rows]
    closes = [float(r[2]) for r in rows]
    out: dict[str, float] = {}
    for i in range(len(closes) - HOLD_DAYS):
        out[dates[i]] = closes[i + HOLD_DAYS] / closes[i] - 1.0
    return out


def institutional_buy_count(event: BillboardEvent) -> int:
    """Institution-only buy seats, from the exchange's EXPLAIN note."""
    return event.institutional_buy_count


def evaluate(name: str, events: list[tuple[float, str]], n_trials: int) -> dict:
    """Per-event returns -> honest statistics, clustered by week.

    The docstring here used to claim "no compounding across overlaps", and that
    was true of the *returns* — each event was measured on its own, nothing was
    chained. But the standard error still divided by ``sqrt(n)``, which assumes
    the overlaps do not exist. Not compounding the returns and then treating them
    as independent are two different problems; only the first was solved.

    A-share billboard events bunch hard: hundreds of stocks list on the same day
    in the same market-wide flow episode, held for five sessions. Weekly clusters
    are the honest unit.
    """
    usable = [(r, d) for r, d in events if np.isfinite(r)]
    if len(usable) < 100:
        return {"strategy": name, "n": len(usable), "note": "sample too small"}

    result = clustered_inference.analyse(
        [r for r, _ in usable], [d for _, d in usable],
        t_hurdle=deflated_t_stat_threshold(n_trials), hold_days=HOLD_DAYS,
    )
    row = {"strategy": name, **result.to_dict()}
    row["events"] = [{"date": d, "excess": round(r, 6)} for r, d in sorted(usable, key=lambda x: x[1])]
    return row


def main() -> None:
    print("=" * 88)
    print("PRE-REGISTERED EXPERIMENT — A-share dragon-tiger flow (real data)")
    print("=" * 88)

    registry = HypothesisRegistry()
    preregister(registry)
    manifest = run_manifest.pin("billboard_attention_reversal", params={"hold_days": HOLD_DAYS, "cost_bps": COST_BPS, "max_events": MAX_EVENTS})
    print(f"观测时点 as_of = {manifest.as_of.isoformat()}")
    print(f"\n已预注册 2 个竞争假设;累计试验 {registry.n_trials}\n")

    events = fetch_billboard_events(max_events=MAX_EVENTS)
    benchmark = csi300_horizon_returns()
    print(f"真实事件 {len(events)} 条, {min(e.trade_date for e in events)} .. "
          f"{max(e.trade_date for e in events)}")

    # Dedupe: a stock can appear on several trigger rows the same day.
    seen: set[tuple[str, str]] = set()
    rows: list[tuple[BillboardEvent, float]] = []
    for event in events:
        key = (event.trade_date, event.code)
        if key in seen:
            continue
        raw = capturable_return(event, HOLD_DAYS)
        if raw is None:
            continue
        bench = benchmark.get(event.trade_date)
        if bench is None:
            continue
        seen.add(key)
        cost = COST_BPS / 1e4
        rows.append((event, raw - bench - cost))     # excess of market, net of cost
    print(f"去重且有基准+前瞻收益: {len(rows)} 事件\n")

    all_rets = [(r, e.trade_date) for e, r in rows]
    inst = [(r, e.trade_date) for e, r in rows if institutional_buy_count(e) > 0]
    retail = [(r, e.trade_date) for e, r in rows if institutional_buy_count(e) == 0]

    n_trials = registry.n_trials
    results = [
        evaluate("H1 全部上榜(超额,净成本)", all_rets, n_trials),
        evaluate("H2 有机构买入", inst, n_trials),
        evaluate("H2 对照:无机构买入", retail, n_trials),
    ]

    print(f"{'组':26} {'n':>6} {'独立单元':>8} {'平均超额':>9} {'中位':>8} {'胜率':>7} "
          f"{'t(iid)':>8} {'t(聚类)':>8} {'t门槛':>6}  显著?")
    for r in results:
        if "mean_excess_pct" not in r:
            print(f"{r['strategy']:26} {r['n']:>6}  {r.get('note')}")
            continue
        print(f"{r['strategy']:26} {r['n']:>6} {r['n_clusters']:>8} "
              f"{r['mean_excess_pct']:>8.2f}% {r['median_excess_pct']:>7.2f}% "
              f"{r['win_rate']*100:>6.1f}% {r['t_stat_iid']:>8.2f} {r['t_stat']:>8.2f} "
              f"{r['t_hurdle']:>6.2f}  {'✅' if r['significant'] else '❌'}")
        for warning in r.get("warnings", []):
            print(f"{'':26} ⚠ {warning}")

    # Sub-period stability: a 4-month window could be one unusual stretch, so
    # report the effect month by month. A real behavioural effect should show up
    # in most months, not be carried by one.
    by_month: dict[str, list[float]] = defaultdict(list)
    for event, ret in rows:
        by_month[event.trade_date[:7]].append(ret)
    print(f"\n分月稳定性(全部上榜, 超额净成本):")
    for month in sorted(by_month):
        vals = np.array(by_month[month])
        if len(vals) < 50:
            continue
        print(f"  {month}  n={len(vals):5}  平均 {vals.mean()*100:+6.2f}%  "
              f"胜率 {(vals > 0).mean()*100:5.1f}%")

    # PBO across time blocks: does the effect hold in every sub-period, or is it
    # one lucky stretch? Configs = the three groups, periods = event order.
    try:
        legs = [[r for r, _ in group] for group in (all_rets, inst, retail)]
        length = min(len(leg) for leg in legs)
        if length >= 200:
            matrix = np.array([leg[:length] for leg in legs])
            pbo = probability_of_backtest_overfitting(matrix, n_blocks=10)
            print(f"\nPBO(组间选择) = {pbo.pbo:.2f} -> {pbo.verdict}")
    except Exception as exc:  # noqa: BLE001
        print(f"\nPBO 无法计算: {exc}")

    # Per-year win rates: the board cites the coverage as evidence, so it has to
    # come from the run rather than from a sentence someone typed.
    by_year: dict[str, dict] = {}
    for year in sorted({e.trade_date[:4] for e, _ in rows}):
        vals = np.array([r for e, r in rows if e.trade_date[:4] == year])
        if len(vals) < 50:
            continue
        by_year[year] = {"n": int(len(vals)), "mean_excess_pct": round(float(vals.mean()) * 100, 3),
                         "win_rate": round(float((vals > 0).mean()), 4)}

    dates = [e.trade_date for e, _ in rows]
    out = Path("data/billboard_results.json")
    out.write_text(json.dumps({
        "generated_at": datetime.now(UTC).isoformat(), "real_data_only": True,
        "hold_days": HOLD_DAYS, "cost_bps": COST_BPS, "n_events": len(rows),
        "n_trials": n_trials,
        "coverage": {"start": min(dates), "end": max(dates)} if dates else {},
        "by_year": by_year,
        "inference": "cluster_robust",   # the board refuses rows without this
        "results": results,
    }, indent=2, ensure_ascii=False))
    for r in results:
        registry.record_result(
            "billboard_attention_reversal" if r["strategy"].startswith("H1")
            else "billboard_institutional_flow",
            {k: v for k, v in r.items() if k != "events"})
    written = manifest.save(out)
    print(f"\n写入 {out}")
    print(f"运行清单 {written}")
    for warning in manifest.warn_lines():
        print(f"  ⚠ {warning}")
    print("\n实施性提醒:A股个股做空受限,H1 若成立应作为'回避过滤器'使用,而非做空策略。")


if __name__ == "__main__":
    main()
