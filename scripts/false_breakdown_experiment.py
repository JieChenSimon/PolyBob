"""Pre-registered experiment: is the book's "false breakdown" setup real?

《炒股的智慧》 calls this its highest-conviction pattern and claims it makes money
"十次有九次" — ten times out of nine. That is an extraordinary claim (a 90% win
rate is far outside anything the empirical literature reports for a chart
pattern), and the project already ships it as a BUY signal in
``strategies/trading_wisdom.py``. So it gets measured on real data before it is
allowed anywhere near the verdict engine.

Two competing, theory-driven hypotheses, registered before the results are seen,
and both reported whatever they show:

- **H1 stop-run reversal.** Stop-loss orders cluster just below visible support,
  because that is where every chart reader puts them. A push through support
  triggers forced, *non-informational* selling; once the stops are exhausted the
  price snaps back. Predicts POSITIVE excess return after a break-and-recover.
- **H2 broken support is information.** A support break is genuine deterioration
  and the intraday recovery is a dead-cat bounce. Predicts ZERO or NEGATIVE
  excess return.

They make opposite predictions on the same events, so the data can falsify at
least one. That is the point of writing them down first.

Discipline applied throughout:

- **The predicate is the shipped one.** ``false_breakdown_at`` reproduces the
  exact rule in ``strategies/trading_wisdom.py`` at an arbitrary index, and
  ``tests/test_false_breakdown_experiment.py`` asserts the two agree on the final
  bar. Validating a lookalike rule would prove nothing about what the app does.
- **Causal by construction.** Support uses ``low[i-lookback : i-2]``, entry is at
  the signal bar's close, exit at the close ``HOLD_DAYS`` later. Nothing after
  the entry bar is consulted to decide the entry.
- **Benchmarked.** Excess is measured against that domain's market over the same
  dates (CSI 300 / SPY / BTC-USDT), so a bull market is never mistaken for a
  pattern working.
- **Cost-netted**, per domain, round trip.
- **Non-overlapping events per symbol.** Two entries four days apart share three
  days of outcome; counting both inflates the t-stat.
- **Date-clustered t-stat is the one that decides.** Market-wide selloffs make
  hundreds of symbols break support on the same day, so events are not
  independent draws. The naive cross-sectional t is reported too — the gap
  between them is itself the finding.
- **Controls.** True breakdowns (broke support, did *not* recover) isolate
  whether the recovery carries the information; the unconditional base rate
  says whether the pattern beats simply being long.
- Every trial counts toward the deflated t-hurdle.

Run: ``python scripts/false_breakdown_experiment.py``
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from libs.data.real_sources import (
    DataUnavailable,
    DailyBars,
    fetch_a_share_daily,
    fetch_altcoin_daily,
    fetch_us_equity_daily,
)
from libs.quant.hypothesis import Hypothesis, HypothesisRegistry, Rationale
from libs.quant.pbo import deflated_t_stat_threshold

# --- pre-registered parameters (fixed before any result is looked at) --------
HOLD_DAYS = 5                # primary horizon
SECONDARY_HORIZONS = (10, 20)
LOOKBACK = 60                # the shipped default in detect_signals
SWING_WINDOW = 5
VOLUME_CONFIRM = 1.2         # "只有在交易量增加的前提下"
MIN_BARS = 260

COST_BPS = {"a_share": 30.0, "us_equity": 10.0, "altcoin": 20.0}
# CSI 300 must be spelled with its exchange prefix: a bare "000300" infers to
# Shenzhen and would silently benchmark against a different instrument.
BENCHMARK = {"a_share": "sh000300", "us_equity": "SPY", "altcoin": "BTC-USDT"}

# Universe. Chosen for breadth and liquidity, not by looking at results.
# NOTE (survivorship): these are instruments listed *today*. Names that went to
# zero are absent, which biases every long-side result upward. The bias applies
# equally to the signal group and its controls, so the *difference* between them
# is the trustworthy number — which is exactly why the controls are here.
US_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "JPM", "V",
    "UNH", "XOM", "JNJ", "WMT", "MA", "PG", "HD", "CVX", "ABBV", "MRK",
    "KO", "PEP", "BAC", "COST", "TMO", "CSCO", "MCD", "ACN", "ABT", "DHR",
    "LIN", "ADBE", "TXN", "NKE", "WFC", "DIS", "PM", "VZ", "CMCSA", "NEE",
    "RTX", "INTC", "AMD", "QCOM", "HON", "UPS", "T", "LOW", "SPGI", "INTU",
    "CAT", "GS", "BA", "BLK", "DE", "MS", "AXP", "GE", "MMM", "F",
]
ALT_UNIVERSE = [
    "SOL-USDT", "ETH-USDT", "DOGE-USDT", "ADA-USDT", "AVAX-USDT", "LINK-USDT",
    "LTC-USDT", "XRP-USDT", "DOT-USDT", "ATOM-USDT", "UNI-USDT", "FIL-USDT",
    "ETC-USDT", "NEAR-USDT", "APT-USDT", "OP-USDT", "ARB-USDT", "SUI-USDT",
    "TRX-USDT", "BCH-USDT",
]
A_SHARE_UNIVERSE = [
    "600519", "600036", "601318", "600900", "600276", "601899", "600030", "600887",
    "601166", "600028", "601288", "601398", "601988", "600016", "600000", "601628",
    "600585", "600690", "601012", "600309", "600009", "600104", "601088", "601857",
    "601390", "601668", "601186", "600050", "600011", "600703", "600745", "600438",
    "000001", "000002", "000063", "000100", "000157", "000333", "000338", "000568",
    "000651", "000725", "000776", "000858", "002001", "002007", "002027", "002032",
    "002049", "002050", "002230", "002236", "002304", "002352", "002415", "002460",
    "002466", "002475", "002493", "002594",
]


def preregister(registry: HypothesisRegistry) -> None:
    registry.register(Hypothesis(
        hypothesis_id="false_breakdown_stop_run",
        claim=("A break below recent support that closes back above it is followed by "
               "positive excess returns over the next week."),
        rationale=Rationale.STRUCTURAL,
        mechanism=("Stops cluster immediately below visible support because that is where "
                   "chart readers place them. Sweeping that cluster forces selling that "
                   "carries no information about value; once exhausted, the imbalance "
                   "reverses. It survives arbitrage because supplying liquidity into a "
                   "cascade requires capital precisely when risk appears highest."),
        literature=("Liquidity-provision premia after forced selling, and short-horizon "
                    "reversal following non-informational order flow, are documented "
                    "across equity and crypto markets."),
        direction="long_after_support_recovery",
        universe="US large caps + A-share liquid names + major altcoins",
        horizon_days=HOLD_DAYS, cost_bps=COST_BPS["us_equity"],
    ))
    registry.register(Hypothesis(
        hypothesis_id="false_breakdown_is_noise",
        claim=("Break-and-recover events carry no exploitable information; excess returns "
               "are indistinguishable from zero once costs and the market are removed."),
        rationale=Rationale.STRUCTURAL,
        mechanism=("Support levels are visible to everyone, so any predictable bounce is "
                   "competed away by faster participants. What remains is a pattern that "
                   "looks compelling in hindsight because losing instances stop being "
                   "drawn on the chart."),
        literature=("Chart patterns without a flow-based mechanism are the part of the "
                    "factor zoo that fails to replicate out of sample."),
        direction="no_position",
        universe="US large caps + A-share liquid names + major altcoins",
        horizon_days=HOLD_DAYS, cost_bps=COST_BPS["us_equity"],
    ))


# ------------------------------------------------------------------ predicate
def false_breakdown_at(
    low: np.ndarray, close: np.ndarray, i: int, lookback: int = LOOKBACK
) -> bool:
    """The shipped FALSE_BREAKDOWN rule, evaluated at bar ``i``.

    Mirrors ``strategies.trading_wisdom.detect_signals`` exactly — see the module
    docstring for why that matters. Uses only data up to and including ``i``.
    """
    if i <= 5:
        return False
    support = float(np.min(low[max(0, i - lookback) : i - 2]))
    if support <= 0:
        return False
    broke = bool(np.any(low[max(0, i - 3) : i + 1] < support))
    return broke and bool(close[i] > support)


def broke_without_recovery_at(
    low: np.ndarray, close: np.ndarray, i: int, lookback: int = LOOKBACK
) -> bool:
    """The control: support was breached and the close did *not* reclaim it."""
    if i <= 5:
        return False
    support = float(np.min(low[max(0, i - lookback) : i - 2]))
    if support <= 0:
        return False
    broke = bool(np.any(low[max(0, i - 3) : i + 1] < support))
    return broke and bool(close[i] <= support)


def volume_confirmed_at(volume: np.ndarray, i: int, window: int = 20) -> bool:
    """``_volume_ratio(...) >= 1.2``, the book's volume precondition."""
    if i < window:
        return False
    baseline = float(volume[i - window : i].mean())
    if baseline <= 0:
        return False
    return float(volume[i] / baseline) >= VOLUME_CONFIRM


# ------------------------------------------------------------------ benchmarks
def benchmark_returns(domain: str, horizon: int) -> dict[str, float]:
    """{date: forward ``horizon``-bar return} for the domain's market."""
    symbol = BENCHMARK[domain]
    if domain == "a_share":
        bars = fetch_a_share_daily(symbol)
    elif domain == "us_equity":
        bars = fetch_us_equity_daily(symbol)
    else:
        bars = fetch_altcoin_daily(symbol)
    closes = bars.closes
    return {
        bars.dates[i]: closes[i + horizon] / closes[i] - 1.0
        for i in range(len(closes) - horizon)
        if closes[i] > 0
    }


# --------------------------------------------------------------------- events
class Event:
    __slots__ = ("symbol", "domain", "date", "excess", "volume_ok", "group")

    def __init__(self, symbol, domain, date, excess, volume_ok, group):
        self.symbol, self.domain, self.date = symbol, domain, date
        self.excess, self.volume_ok, self.group = excess, volume_ok, group


def scan(bars: DailyBars, horizon: int, bench: dict[str, float]) -> list[Event]:
    """Non-overlapping signal and control events for one instrument."""
    if len(bars) < MIN_BARS or bars.lows is None or bars.volumes is None:
        return []
    low = np.asarray(bars.lows, dtype=float)
    close = np.asarray(bars.closes, dtype=float)
    volume = np.asarray(bars.volumes, dtype=float)
    cost = COST_BPS[bars.domain] / 1e4

    events: list[Event] = []
    last_taken: dict[str, int] = {}
    for i in range(LOOKBACK + SWING_WINDOW, len(close) - horizon):
        if false_breakdown_at(low, close, i):
            group = "signal"
        elif broke_without_recovery_at(low, close, i):
            group = "control_breakdown"
        else:
            continue
        # Overlapping outcomes are not independent observations.
        if i - last_taken.get(group, -10**9) < horizon:
            continue
        market = bench.get(bars.dates[i])
        if market is None or close[i] <= 0:
            continue
        last_taken[group] = i
        raw = close[i + horizon] / close[i] - 1.0
        events.append(Event(bars.symbol, bars.domain, bars.dates[i],
                            raw - market - cost, volume_confirmed_at(volume, i), group))
    return events


def base_rate_events(bars: DailyBars, horizon: int, bench: dict[str, float]) -> list[Event]:
    """Unconditional every-``horizon``-bars sample — "just be long" as a control."""
    if len(bars) < MIN_BARS:
        return []
    close = np.asarray(bars.closes, dtype=float)
    cost = COST_BPS[bars.domain] / 1e4
    out: list[Event] = []
    for i in range(LOOKBACK + SWING_WINDOW, len(close) - horizon, horizon):
        market = bench.get(bars.dates[i])
        if market is None or close[i] <= 0:
            continue
        raw = close[i + horizon] / close[i] - 1.0
        out.append(Event(bars.symbol, bars.domain, bars.dates[i],
                         raw - market - cost, False, "control_baserate"))
    return out


# ----------------------------------------------------------------- statistics
def date_clustered_t(events: list[Event]) -> tuple[float, int]:
    """t-stat over per-date means, and the number of independent dates.

    A market-wide selloff makes hundreds of names break support the same day.
    Treating those as independent draws is the single easiest way to manufacture
    significance out of one bad week.
    """
    by_date: dict[str, list[float]] = defaultdict(list)
    for e in events:
        by_date[e.date].append(e.excess)
    daily = np.array([float(np.mean(v)) for v in by_date.values()])
    if len(daily) < 3:
        return 0.0, len(daily)
    sd = daily.std(ddof=1)
    if sd == 0:
        return 0.0, len(daily)
    return float(daily.mean() / (sd / np.sqrt(len(daily)))), len(daily)


def evaluate(name: str, events: list[Event], n_trials: int) -> dict:
    rets = np.array([e.excess for e in events], dtype=float)
    rets = rets[np.isfinite(rets)]
    if len(rets) < 30:
        return {"group": name, "n": int(len(rets)), "note": "sample too small to judge"}
    naive_sd = rets.std(ddof=1)
    naive_t = float(rets.mean() / (naive_sd / np.sqrt(len(rets)))) if naive_sd > 0 else 0.0
    clustered_t, n_dates = date_clustered_t(events)
    hurdle = deflated_t_stat_threshold(n_trials)
    return {
        "group": name,
        "n": int(len(rets)),
        "n_dates": n_dates,
        "mean_excess_pct": round(float(rets.mean()) * 100, 3),
        "median_excess_pct": round(float(np.median(rets)) * 100, 3),
        "win_rate": round(float((rets > 0).mean()), 4),
        "t_naive": round(naive_t, 2),
        "t_clustered": round(clustered_t, 2),
        "t_hurdle": round(hurdle, 2),
        "significant": bool(abs(clustered_t) >= hurdle),
    }


def _print_table(title: str, rows: list[dict]) -> None:
    print(f"\n{title}")
    print(f"{'组':30} {'n':>6} {'独立日':>6} {'平均超额':>9} {'中位':>8} {'胜率':>7} "
          f"{'t朴素':>7} {'t聚类':>7} {'门槛':>6}  显著?")
    for r in rows:
        if "mean_excess_pct" not in r:
            print(f"{r['group']:30} {r['n']:>6}  {r.get('note')}")
            continue
        print(f"{r['group']:30} {r['n']:>6} {r['n_dates']:>6} {r['mean_excess_pct']:>8.2f}% "
              f"{r['median_excess_pct']:>7.2f}% {r['win_rate']*100:>6.1f}% "
              f"{r['t_naive']:>7.2f} {r['t_clustered']:>7.2f} {r['t_hurdle']:>6.2f}  "
              f"{'✅' if r['significant'] else '❌'}")


def collect(horizon: int) -> list[Event]:
    """Every event across all three domains at one horizon."""
    plan = [
        ("a_share", A_SHARE_UNIVERSE, fetch_a_share_daily),
        ("us_equity", US_UNIVERSE, fetch_us_equity_daily),
        ("altcoin", ALT_UNIVERSE, fetch_altcoin_daily),
    ]
    events: list[Event] = []
    for domain, universe, fetcher in plan:
        try:
            bench = benchmark_returns(domain, horizon)
        except DataUnavailable as exc:
            print(f"  {domain}: 基准不可用，跳过（绝不用假数据代替）— {exc}")
            continue
        ok = 0
        for symbol in universe:
            try:
                bars = fetcher(symbol)
            except (DataUnavailable, Exception) as exc:  # noqa: BLE001
                print(f"    {symbol}: {type(exc).__name__} — 跳过")
                continue
            found = scan(bars, horizon, bench) + base_rate_events(bars, horizon, bench)
            if found:
                ok += 1
                events.extend(found)
        print(f"  {domain}: {ok}/{len(universe)} 标的有可用真实数据")
    return events


def main() -> None:
    print("=" * 92)
    print("预注册实验 —— 《炒股的智慧》「假突破反转」是否真实存在(全真实数据)")
    print("=" * 92)

    registry = HypothesisRegistry()
    preregister(registry)
    horizons = (HOLD_DAYS, *SECONDARY_HORIZONS)
    # Each horizon x each group is a look at the data; the hurdle must know.
    n_trials = registry.n_trials + len(horizons) * 3
    print(f"\n已预注册 2 个竞争假设；连同 {len(horizons)} 个持有期 × 3 组，"
          f"累计试验 {n_trials}，t 门槛 {deflated_t_stat_threshold(n_trials):.2f}\n")

    results: dict[str, list[dict]] = {}
    all_events: dict[int, list[Event]] = {}
    for horizon in horizons:
        label = "主检验" if horizon == HOLD_DAYS else "次要"
        print(f"\n--- 持有 {horizon} 日（{label}）---")
        events = collect(horizon)
        all_events[horizon] = events
        signal = [e for e in events if e.group == "signal"]
        rows = [
            evaluate("假突破反转(全部)", signal, n_trials),
            evaluate("  └ 放量确认子集", [e for e in signal if e.volume_ok], n_trials),
            evaluate("  └ 未放量子集", [e for e in signal if not e.volume_ok], n_trials),
            evaluate("对照:破位未收回", [e for e in events if e.group == "control_breakdown"], n_trials),
            evaluate("对照:无条件基准率", [e for e in events if e.group == "control_baserate"], n_trials),
        ]
        _print_table(f"持有 {horizon} 日，超额于大盘、已扣成本", rows)
        results[f"h{horizon}"] = rows

    # Per-domain and per-year breakdown at the primary horizon: a real structural
    # effect should not live in one market or one year.
    primary = [e for e in all_events[HOLD_DAYS] if e.group == "signal"]
    by_domain = [evaluate(f"  {d}", [e for e in primary if e.domain == d], n_trials)
                 for d in ("a_share", "us_equity", "altcoin")]
    _print_table("分市场（主检验，假突破反转）", by_domain)
    results["by_domain"] = by_domain

    years = sorted({e.date[:4] for e in primary})
    by_year = [evaluate(f"  {y}", [e for e in primary if e.date[:4] == y], n_trials)
               for y in years]
    _print_table("分年度（主检验，假突破反转）", by_year)
    results["by_year"] = by_year

    # The book's actual claim, stated in the book's own terms.
    vol = [e for e in primary if e.volume_ok]
    if vol:
        wr = float(np.mean([e.excess > 0 for e in vol]))
        print(f"\n书中原话是「十次有九次赚钱」= 90% 胜率。")
        print(f"放量确认子集的真实胜率：{wr*100:.1f}%（n={len(vol)}，超额于大盘、已扣成本）")

    out = Path("data/false_breakdown_results.json")
    out.write_text(json.dumps({
        "generated_at": datetime.now(UTC).isoformat(),
        "real_data_only": True,
        "primary_horizon": HOLD_DAYS,
        "secondary_horizons": list(SECONDARY_HORIZONS),
        "cost_bps": COST_BPS,
        "benchmarks": BENCHMARK,
        "n_trials": n_trials,
        "t_hurdle": round(deflated_t_stat_threshold(n_trials), 2),
        "decided_on": "t_clustered",
        "results": results,
        "caveats": [
            "Universes are instruments listed today; delisted names are absent, "
            "which biases long-side results upward. Compare groups, not levels.",
            "Events are date-clustered; t_clustered is the honest statistic.",
        ],
    }, indent=2, ensure_ascii=False))
    for row in results["h5"]:
        registry.record_result(
            "false_breakdown_stop_run" if row["group"].startswith("假突破")
            else "false_breakdown_is_noise", row)
    print(f"\n写入 {out}")


if __name__ == "__main__":
    main()
