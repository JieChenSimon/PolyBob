"""Does a gate-approved edge apply to *this instrument, right now*?

The verdict engine used to answer a different question than the one it printed.
It asked the promotion registry "are there any approved edges in this asset
class?", and if the answer was yes it told you, on any US stock you happened to
open, that a *validated edge* backed the trade. But the one approved US edge is
an **event** edge: it exists on a specific ticker on the days after several
insiders file open-market purchases. On a ticker with no such filing there is no
edge, and saying otherwise is not a rounding error — it is the difference
between a measured 53% win rate and a coin flip.

The same holds the other way for altcoins: retail crowding is a state a
particular coin is in on a particular day, not a property of "altcoins".

So an edge is only claimable here when its **triggering event is detected on
this instrument within the window the study measured**. Three outcomes, and the
third matters as much as the others:

- ``ACTIVE``   — the event fired on this instrument, inside the horizon.
- ``INACTIVE`` — checked against real data, no event. Not an edge right now.
- ``UNKNOWN``  — the data needed to check was unavailable. Never reported as
  "no edge" and never as "edge": an unchecked condition is not a clean one.

That last distinction is what the A-share trap check got wrong: it reported a
clean PASS for every stock while never once fetching the dragon-tiger list.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import Enum
from typing import Any, Callable


class EdgeStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    UNKNOWN = "unknown"


class Direction(str, Enum):
    """Which way an edge says to act.

    An edge without a direction is not actionable. The altcoin edge is
    short-only: its validated leg is a funded perp short, and the verdict engine
    used to have no way to express that, so the highest-returning edge on the
    board (+3.20%, 68.4% win rate) rendered as "回避" — "avoid" — at precisely
    the moment it was an entry.
    """

    LONG = "long"
    SHORT = "short"
    AVOID = "avoid"      # a filter: it tells you not to buy, it is not a position


# How each approved edge says to act. Read from the board's ``implementation``
# so the direction and the evidence can never drift apart: an edge validated as
# a short must not be renderable as anything else.
_IMPLEMENTATION_DIRECTION: dict[str, Direction] = {
    "long_after_cluster_filing": Direction.LONG,
    "short_perp_when_retail_crowded_long": Direction.SHORT,
    "avoidance_filter_only_no_shorting": Direction.AVOID,
    "take_side_when_model_beats_market_price": Direction.LONG,
}


def direction_for(strategy: str) -> Direction | None:
    """The board's own word on which way this edge trades, or ``None``."""
    from libs.quant.promotion_registry import get_registry

    for record in get_registry().records():
        if record.strategy == strategy:
            return _IMPLEMENTATION_DIRECTION.get(record.implementation)
    return None


@dataclass(frozen=True)
class EdgeInstance:
    """Whether one approved edge applies to one instrument now, and why."""

    strategy: str
    instrument: str
    status: EdgeStatus
    evidence_zh: str
    evidence_en: str
    detail: dict[str, Any] | None = None
    direction: Direction | None = None

    @property
    def is_active(self) -> bool:
        return self.status is EdgeStatus.ACTIVE

    @property
    def is_tradable(self) -> bool:
        """Firing *and* pointing at a position you could actually open."""
        return self.is_active and self.direction in (Direction.LONG, Direction.SHORT)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "instrument": self.instrument,
            "status": self.status.value,
            "direction": self.direction.value if self.direction else None,
            "evidence_zh": self.evidence_zh,
            "evidence_en": self.evidence_en,
            "detail": self.detail or {},
        }


def _unknown(strategy: str, symbol: str, reason: str) -> EdgeInstance:
    return EdgeInstance(
        strategy, symbol, EdgeStatus.UNKNOWN,
        f"无法验证该边是否在 {symbol} 上触发：{reason}",
        f"Could not check whether this edge fired on {symbol}: {reason}",
        direction=direction_for(strategy),
    )


# --------------------------------------------------------------- US insiders
def detect_insider_cluster(
    symbol: str,
    *,
    as_of: date | None = None,
    window_days: int = 20,
    min_insiders: int = 2,
    min_value_usd: float = 50_000.0,
    trade_source: Callable[[int, int], list] | None = None,
    allow_fetch: bool = False,
) -> EdgeInstance:
    """Did ≥2 insiders file open-market buys on ``symbol`` recently?

    ``window_days`` matches the study's 20-session holding period: inside it the
    measured drift is still ahead of you, outside it the event has already played
    out and entering now is a different trade from the one that was validated.

    Two data paths, because the two questions need different endpoints:

    - **Live** (default): EDGAR's daily filing index, published the same evening.
      This is the only path that can see a filing inside the twenty-day window.
    - **Historical**: pass ``trade_source`` to read the quarterly Form 345 bulk
      datasets instead. That is what the backtest used; it lags a quarter, so it
      cannot answer "is this firing now".

    ``allow_fetch`` is off by default: warming a cold window costs thousands of
    requests and must never happen inside a page load. Run
    ``scripts/warm_insider_cache.py`` on a schedule instead.
    """
    if trade_source is None:
        return _detect_insider_cluster_live(
            symbol, as_of=as_of, window_days=window_days, allow_fetch=allow_fetch
        )

    from libs.data.sec_insider import SecDataUnavailable, cluster_buys, fetch_insider_trades

    strategy = "us_insider_cluster_buy"
    as_of = as_of or datetime.now(UTC).date()
    fetch = trade_source or fetch_insider_trades
    start = as_of - timedelta(days=window_days)

    quarters: list[tuple[int, int]] = []
    year, quarter = start.year, (start.month - 1) // 3 + 1
    while (year, quarter) <= (as_of.year, (as_of.month - 1) // 3 + 1):
        quarters.append((year, quarter))
        year, quarter = (year + 1, 1) if quarter == 4 else (year, quarter + 1)

    trades: list = []
    failures = 0
    for y, q in quarters:
        try:
            trades.extend(fetch(y, q))
        except SecDataUnavailable:
            failures += 1
    if failures == len(quarters):
        # Known structural limit, not a transient outage: the Form 345 *bulk*
        # datasets are published weeks after a quarter closes, so the quarter
        # containing a filing from the last 20 days is normally not out yet. The
        # study was valid on historical data; live detection needs EDGAR's daily
        # feed. Saying so beats a bare "unavailable" that reads like a blip.
        return _unknown(
            strategy, symbol,
            f"SEC Form 345 季度批量数据尚未发布（需要 {', '.join(f'{y}Q{q}' for y, q in quarters)}）。"
            "该数据集在季度结束数周后才发布，因此最近 20 天的申报天然查不到——"
            "实时检测需要接入 EDGAR 每日申报流，当前尚未接入",
        )

    wanted = symbol.strip().upper()
    clusters = cluster_buys(trades, min_insiders=min_insiders, min_value_usd=min_value_usd)
    hits = [
        (sym, filed, value) for (sym, filed), value in clusters.items()
        if sym == wanted and filed and start.isoformat() <= filed <= as_of.isoformat()
    ]
    if not hits:
        return EdgeInstance(
            strategy, symbol, EdgeStatus.INACTIVE,
            f"{symbol} 最近 {window_days} 天没有内部人集群买入申报——该边此刻不适用",
            f"No insider cluster filing on {symbol} in the last {window_days} days — "
            "the edge does not apply right now",
            {"window_days": window_days, "clusters_checked": len(clusters)},
            direction=direction_for(strategy),
        )

    hits.sort(key=lambda h: h[1], reverse=True)
    _, filed, value = hits[0]
    return EdgeInstance(
        strategy, symbol, EdgeStatus.ACTIVE,
        f"{symbol} 于 {filed} 有内部人集群买入申报（合计 ${value:,.0f}）——"
        f"该边在本标的上触发，实测持有 20 日超额 +5.11%、胜率 53.2%",
        f"Insider cluster filing on {symbol} dated {filed} (${value:,.0f}) — "
        "edge active; measured +5.11% excess over 20 sessions, 53.2% win rate",
        {"filing_date": filed, "value_usd": value, "window_days": window_days},
        direction=direction_for(strategy),
    )


def _detect_insider_cluster_live(
    symbol: str,
    *,
    as_of: date | None,
    window_days: int,
    allow_fetch: bool,
) -> EdgeInstance:
    """The live path: EDGAR's daily index, with coverage reported honestly."""
    from libs.data.sec_daily_insider import scan_window

    strategy = "us_insider_cluster_buy"
    as_of = as_of or datetime.now(UTC).date()
    scan = scan_window(as_of, window_days, allow_fetch=allow_fetch)
    hits = scan.for_symbol(symbol)

    if hits:
        latest = max(hits, key=lambda e: e.filing_date)
        return EdgeInstance(
            strategy, symbol, EdgeStatus.ACTIVE,
            f"{symbol} 于 {latest.filing_date} 有 {latest.insiders} 名内部人集群买入申报"
            f"（合计 ${latest.value_usd:,.0f}，来源 EDGAR 每日申报）——该边在本标的上触发，"
            f"实测持有 20 日超额 +5.11%、胜率 53.2%",
            f"{latest.insiders} insiders filed open-market purchases of {symbol} on "
            f"{latest.filing_date} (${latest.value_usd:,.0f}, EDGAR daily index) — "
            "edge active; measured +5.11% excess over 20 sessions, 53.2% win rate",
            {"filing_date": latest.filing_date, "value_usd": latest.value_usd,
             "insiders": latest.insiders, "window_days": window_days,
             "days_covered": len(scan.days_covered)},
            direction=direction_for(strategy),
        )

    if scan.complete:
        return EdgeInstance(
            strategy, symbol, EdgeStatus.INACTIVE,
            f"{symbol} 最近 {window_days} 天没有内部人集群买入申报"
            f"（已核对 {len(scan.days_covered)} 个交易日）——该边此刻不适用",
            f"No insider cluster filing on {symbol} in the last {window_days} days "
            f"({len(scan.days_covered)} sessions checked) — the edge does not apply now",
            {"window_days": window_days, "days_covered": len(scan.days_covered)},
            direction=direction_for(strategy),
        )

    # Found nothing, but did not read every day. "No cluster in the days I could
    # read" is not "no cluster", and reporting it as INACTIVE would be the same
    # silent-pass mistake this module exists to prevent.
    missing = ", ".join(scan.days_missing[:3])
    more = f" 等 {len(scan.days_missing)} 天" if len(scan.days_missing) > 3 else ""
    return _unknown(
        strategy, symbol,
        f"EDGAR 每日申报缓存不完整,{missing}{more}未读取（已核对 "
        f"{len(scan.days_covered)} 天）。运行 scripts/warm_insider_cache.py 预热后再判定",
    )


# ------------------------------------------------------------ altcoin crowding
def detect_retail_crowding(
    symbol: str,
    *,
    lookback: int = 30,
    percentile: float = 80.0,
    positioning_source: Callable[[str], list] | None = None,
) -> EdgeInstance:
    """Is retail crowded long on this coin, by the study's own trailing rule?

    Percentiles come from a trailing window so the rule stays causal — the same
    construction the experiment used, not a full-sample threshold that would
    peek at the future.
    """
    from libs.data.flow_signals import SignalDataUnavailable, fetch_retail_positioning

    strategy = "altcoin_retail_crowding"
    fetch = positioning_source or fetch_retail_positioning
    ccy = symbol.split("-")[0].upper()

    try:
        points = fetch(ccy)
    except SignalDataUnavailable as exc:
        return _unknown(strategy, symbol, f"OKX 多空账户比不可用（{exc}）")

    if len(points) < lookback + 1:
        return _unknown(
            strategy, symbol,
            f"多空比历史只有 {len(points)} 天，不足 {lookback + 1} 天，无法判定分位",
        )

    ratios = [p.long_short_ratio for p in points]
    window = sorted(ratios[-(lookback + 1):-1])
    threshold = window[min(int(len(window) * percentile / 100.0), len(window) - 1)]
    latest = points[-1]

    if latest.long_short_ratio > threshold:
        return EdgeInstance(
            strategy, symbol, EdgeStatus.ACTIVE,
            f"{ccy} 散户多空比 {latest.long_short_ratio:.2f} 高于近 {lookback} 日的 "
            f"{percentile:.0f} 分位（{threshold:.2f}）——拥挤做多，实测做空腿 5 日 "
            f"+3.20%、胜率 68.4%（含资金费）",
            f"{ccy} retail long/short {latest.long_short_ratio:.2f} above the "
            f"{percentile:.0f}th percentile of the last {lookback} days ({threshold:.2f}) — "
            "crowded long; measured short leg +3.20% over 5 days, 68.4% win rate",
            {"ratio": latest.long_short_ratio, "threshold": threshold, "date": latest.date},
            direction=direction_for(strategy),
        )
    return EdgeInstance(
        strategy, symbol, EdgeStatus.INACTIVE,
        f"{ccy} 散户多空比 {latest.long_short_ratio:.2f} 未超过 {percentile:.0f} 分位"
        f"（{threshold:.2f}）——没有拥挤,该边此刻不适用",
        f"{ccy} retail long/short {latest.long_short_ratio:.2f} is below the "
        f"{percentile:.0f}th percentile ({threshold:.2f}) — not crowded, edge inactive",
        {"ratio": latest.long_short_ratio, "threshold": threshold, "date": latest.date},
        direction=direction_for(strategy),
    )


# ------------------------------------------------------- A-share dragon-tiger
def detect_billboard_listing(
    symbol: str,
    *,
    as_of: date | None = None,
    window_days: int = 5,
    event_source: Callable[..., list] | None = None,
) -> EdgeInstance:
    """Was this stock published on the dragon-tiger list in the last week?

    This is the *avoidance* finding: 6,446 real events, -2.74% versus the market
    over five sessions. It is not a short (A-shares are hard to borrow), so it
    never grants permission — it only tells you not to buy. The window matches
    the study's five-session horizon.
    """
    from libs.data.a_share_flow import FlowDataUnavailable, fetch_billboard_events

    strategy = "a_share_billboard_reversal"
    as_of = as_of or datetime.now(UTC).date()
    fetch = event_source or fetch_billboard_events
    code = symbol.strip().upper().split(".")[0]

    try:
        events = fetch(max_events=3000)
    except FlowDataUnavailable as exc:
        return _unknown(strategy, symbol, f"龙虎榜数据不可用（{exc}）")

    start = (as_of - timedelta(days=window_days)).isoformat()
    hits = [
        e for e in events
        if getattr(e, "code", "") == code and start <= getattr(e, "trade_date", "") <= as_of.isoformat()
    ]
    if not hits:
        return EdgeInstance(
            strategy, symbol, EdgeStatus.INACTIVE,
            f"{code} 最近 {window_days} 天未上龙虎榜——未触发该回避条件",
            f"{code} has not been on the dragon-tiger list in the last "
            f"{window_days} days — the avoidance condition is not triggered",
            {"window_days": window_days, "events_scanned": len(events)},
            direction=direction_for(strategy),
        )

    latest = max(hits, key=lambda e: e.trade_date)
    return EdgeInstance(
        strategy, symbol, EdgeStatus.ACTIVE,
        f"{code} 于 {latest.trade_date} 上榜龙虎榜——6,446 个真实事件显示上榜后 5 日"
        f"平均跑输大盘 2.74%、胜率仅 35.7%，这是回避信号不是做空信号",
        f"{code} was listed on the dragon-tiger board on {latest.trade_date} — across "
        "6,446 real events the five-day excess return was -2.74% with a 35.7% win "
        "rate; this is a reason not to buy, not a short",
        {"trade_date": latest.trade_date, "window_days": window_days},
        direction=direction_for(strategy),
    )


DETECTORS: dict[str, Callable[..., EdgeInstance]] = {
    "us_insider_cluster_buy": detect_insider_cluster,
    "altcoin_retail_crowding": detect_retail_crowding,
    "a_share_billboard_reversal": detect_billboard_listing,
}


def detect(strategy: str, symbol: str, **kwargs: Any) -> EdgeInstance:
    """Run the detector registered for ``strategy``, or report UNKNOWN.

    An approved edge with no detector cannot be claimed on any instrument: there
    is no way to tell whether it applies, and "we never checked" must not read as
    "it applies".
    """
    detector = DETECTORS.get(strategy)
    if detector is None:
        return _unknown(strategy, symbol, "该边没有实现事件检测器，无法判断是否适用于本标的")
    return detector(symbol, **kwargs)


__all__ = [
    "DETECTORS",
    "EdgeInstance",
    "EdgeStatus",
    "detect",
    "detect_billboard_listing",
    "detect_insider_cluster",
    "detect_retail_crowding",
]
