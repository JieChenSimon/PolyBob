"""投资准则判定 — the honest verdict engine.

《炒股的智慧》: "犯错并不可怕，可怕的是不知自己犯了错，知错却不肯认错就更加不可
救药。" The dangerous state is not being wrong; it is being wrong without knowing.
So this engine's job is not to predict prices — it is to answer, for one
instrument, right now: **do I actually understand this, and am I about to make a
mistake I already know about?**

Seven checks, in the order the book reasons:

1. **看得懂吗 (Do I see it?)** — is the data real, fresh, and from a named source?
   A conclusion drawn on stale or missing data is a guess wearing a suit.
2. **有验证过的优势吗 (Is there a proven edge?)** — has anything for this domain
   cleared the promotion gate on real data? Unvalidated signals are opinions.
3. **风险定义了吗 (Is the risk defined?)** — is there a stop, and is it within the
   book's 20% ceiling? "选买点最重要的是选择止损点."
4. **是否在犯已知的错 (Known mistakes)** — the specific traps this project has
   *measured*: buying into a fresh dragon-tiger listing (-1.83% over 44,750
   events), buying when retail is crowded long (-2.04%), chasing a parabolic run.
5. **顺势还是逆势 (With or against the trend?)** — the book's flattest rule is
   directional: "绝不要在跌势时入市"，"最好在升势或突破阻力线时买入". A verdict that
   ignores trend state can bless a purchase into a collapse, so a downtrend
   blocks ACT outright and an unmeasurable trend cannot support one either.
   See :mod:`libs.quant.trend_state` for how the classification is derived.
6. **量价配合吗 (Does volume confirm the price?)** — price and volume are one
   observation, not two: "价格的涨跌都肯定伴随着交易量的放大和减少". A breakout on
   thin volume "并没有很大意义", and 量增价滞 — heavy volume that produces no price
   progress — is the book's distribution warning. Check 5 answers *which way*;
   this one answers *whether anyone is actually behind the move*. See
   :mod:`libs.quant.volume_state` for the ratio-based derivation.
7. **结论 (Verdict)** — and when the checks disagree, the answer defaults to
   waiting. "有疑问的时候，离场."

The verdict is deliberately conservative and frequently "no action". That is the
point: most of the time there is nothing to do, and a system that always finds a
reason to trade is the thing the book warns against.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from libs.quant.edge_instance import Direction, EdgeInstance, EdgeStatus
from libs.quant.trend_state import TrendClass, TrendState
from libs.quant.volume_state import VolumeState


class Verdict(str, Enum):
    ACT = "act"                    # understood, edge-backed, risk defined
    WATCH = "watch"                # interesting but a condition is unmet
    WAIT = "wait"                  # nothing actionable — the default
    AVOID = "avoid"                # a measured trap is present


class CheckStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    UNKNOWN = "unknown"            # honest "I don't know" — never silently PASS


@dataclass(frozen=True)
class Check:
    key: str
    question_zh: str
    question_en: str
    status: CheckStatus
    finding_zh: str
    finding_en: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "status": self.status.value,
            "question_zh": self.question_zh, "question_en": self.question_en,
            "finding_zh": self.finding_zh, "finding_en": self.finding_en,
        }


@dataclass(frozen=True)
class VerdictReport:
    symbol: str
    domain: str
    verdict: Verdict
    headline_zh: str
    headline_en: str
    checks: list[Check] = field(default_factory=list)
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol, "domain": self.domain,
            "verdict": self.verdict.value,
            "headline_zh": self.headline_zh, "headline_en": self.headline_en,
            "checks": [c.to_dict() for c in self.checks],
            "generated_at": self.generated_at,
        }


# Which measured trap belongs to which market, and where its numbers live. The
# figures themselves are read from the experiment output at call time rather
# than typed in here: hard-coded prose drifts from the data the moment an
# experiment is re-run, and this module's whole claim is that its numbers are
# measured. See :func:`trap_evidence`.
# Every measured trap is a trap *for a direction*. Both of these are mistakes
# you make by **buying**: chasing a fresh dragon-tiger listing, and buying into
# crowded retail longs. Neither says anything against a short — the altcoin one
# is literally the same observation as the short edge, read from the other side.
#
# Ignoring that produced the sharpest contradiction in the product: on a coin
# where the validated short edge was firing, the engine used the same crowding
# event as the trap and printed "回避——你正在犯一个已被真实数据证实的错误" over
# the top of a +3.20% / 68.4% entry.
KNOWN_TRAPS: dict[str, dict[str, Any]] = {
    "a_share": {
        "name_zh": "龙虎榜上榜后追高",
        "name_en": "buying a fresh dragon-tiger listing",
        "source": "data/billboard_results.json",
        "row": "H1 全部上榜(超额,净成本)",
        "blocks": Direction.LONG,
    },
    "altcoin": {
        "name_zh": "散户极度做多时买入",
        "name_en": "buying when retail is crowded long",
        "source": "data/us_crypto_results.json",
        "row": "散户极度做多后(预期跌)",
        "blocks": Direction.LONG,
    },
}

# How stale daily data may be before a market's conclusion stops being about the
# present. Altcoins trade 24/7, so yesterday's bar is already old; equity markets
# have weekends and holidays, so a few sessions is normal.
STALE_LIMIT_DAYS: dict[str, int] = {
    "altcoin": 2,
    "a_share": 5,
    "us_equity": 5,
}
DEFAULT_STALE_LIMIT_DAYS = 5


def trap_evidence(domain: str) -> tuple[str, str]:
    """The measured numbers behind a domain's trap, straight from its result file.

    Returns ``("", "")`` when the file is missing or does not carry the row —
    the caller then states the trap without fake precision rather than quoting a
    figure nobody can reproduce.
    """
    import json
    from pathlib import Path

    trap = KNOWN_TRAPS.get(domain)
    if not trap:
        return "", ""
    try:
        payload = json.loads(Path(trap["source"]).read_text())
    except Exception:  # noqa: BLE001 - absence of evidence is not evidence
        return "", ""
    for row in payload.get("results", []):
        if str(row.get("strategy")) != trap["row"]:
            continue
        n = row.get("n")
        mean = row.get("mean_excess_pct")
        win = row.get("win_rate")
        if n is None or mean is None or win is None:
            return "", ""
        hold = payload.get("hold_days", "?")
        return (
            f"{n:,} 个真实事件：持有 {hold} 日平均 {mean:+.2f}%，胜率 {win * 100:.1f}%",
            f"{n:,} real events: {mean:+.2f}% over {hold} sessions, "
            f"{win * 100:.1f}% win rate",
        )
    return "", ""


def _stale_days(as_of: str | None, now: datetime | None = None) -> int | None:
    if not as_of:
        return None
    try:
        seen = datetime.fromisoformat(as_of[:10]).replace(tzinfo=UTC)
    except ValueError:
        return None
    return (( now or datetime.now(UTC)) - seen).days


def _side_zh(direction: Direction) -> str:
    return "做空" if direction is Direction.SHORT else "行动"


def _edge_names(edges: list[EdgeInstance]) -> str:
    return "、".join(e.strategy for e in edges)


def _edge_names_en(edges: list[EdgeInstance]) -> str:
    return ", ".join(e.strategy for e in edges)


def _invert_trend(trend: TrendState | None) -> TrendState | None:
    """Read the same trend from a short seller's seat.

    A short is with the trend in a downtrend and against it in an uptrend, so
    the classification mirrors while the *evidence text stays as measured* — the
    numbers describe the instrument, not the position, and rewriting them would
    be fabricating a second reading of the same data.
    """
    if trend is None or trend.classification is TrendClass.UNKNOWN:
        return trend
    mirror = {
        TrendClass.STRONG_UPTREND: TrendClass.STRONG_DOWNTREND,
        TrendClass.UPTREND: TrendClass.DOWNTREND,
        TrendClass.NEUTRAL: TrendClass.NEUTRAL,
        TrendClass.DOWNTREND: TrendClass.UPTREND,
        TrendClass.STRONG_DOWNTREND: TrendClass.STRONG_UPTREND,
    }
    return replace(trend, classification=mirror[trend.classification])


_TREND_Q_ZH = "顺势还是逆势？"
_TREND_Q_EN = "With or against the trend?"


def _trend_check(trend: TrendState | None, direction: Direction = Direction.LONG) -> Check:
    """Map a trend state onto the check semantics, for the direction being traded.

    ``PASS`` only for a trend that runs *with* the intended position, ``FAIL``
    when it runs against it, ``WARN`` for a directionless market (a signal there
    is a coin flip, not an edge), and ``UNKNOWN`` when history is too short to
    say — never a silent ``PASS``, because "I could not measure it" and "it is
    fine" are different claims and confusing them is exactly the error the book
    warns about.

    The book's rule — "绝不要在跌势时入市" — is stated for buying, and its mirror
    is the same discipline, not a new one: never short into a rising market. The
    engine used to have only the buying half, which is how a validated
    short-only edge ended up rendered as "avoid".
    """
    if direction is Direction.SHORT:
        trend = _invert_trend(trend)
    if trend is None or trend.classification is TrendClass.UNKNOWN:
        zh = trend.evidence_zh if trend else "没有足够的历史数据判断趋势——不猜方向"
        en = (trend.evidence_en if trend else
              "Not enough history to judge the trend — the direction is unknown")
        return Check("trend", _TREND_Q_ZH, _TREND_Q_EN, CheckStatus.UNKNOWN, zh, en)

    if trend.blocks_act:
        return Check("trend", _TREND_Q_ZH, _TREND_Q_EN, CheckStatus.FAIL,
                     f"逆势——{trend.evidence_zh}。书中：绝不要在跌势时入市",
                     f"Against the trend — {trend.evidence_en}. "
                     "The book: never enter during a downtrend")

    if trend.supports_act:
        return Check("trend", _TREND_Q_ZH, _TREND_Q_EN, CheckStatus.PASS,
                     f"顺势——{trend.evidence_zh}。书中：最好在升势或突破阻力线时买入",
                     f"With the trend — {trend.evidence_en}. "
                     "The book: buy in an uptrend or on a break of resistance")

    return Check("trend", _TREND_Q_ZH, _TREND_Q_EN, CheckStatus.WARN,
                 f"无明确趋势——{trend.evidence_zh}。方向未确认，不构成买入理由",
                 f"No clear trend — {trend.evidence_en}. "
                 "Direction is unconfirmed, which is not a reason to buy")


_VOLUME_Q_ZH = "量价配合吗？"
_VOLUME_Q_EN = "Does volume confirm the price?"


def _volume_check(volume: VolumeState | None) -> Check:
    """Map a volume state onto the check semantics.

    ``PASS`` only when volume actively confirms an advance, ``FAIL`` for the two
    states the book names as tops (量增价滞 distribution, and a volume climax),
    ``WARN`` for divergence, a dry-up, or simply no confirmation — thin
    participation makes a breakout "并没有很大意义" — and ``UNKNOWN`` when there
    is no usable volume series at all (Polymarket BTC-5m has no bar volume and
    none is invented for it). ``UNKNOWN`` is never a silent ``PASS``: "I could
    not measure participation" and "participation is there" are different claims.
    """
    if volume is None or not volume.available:
        zh = volume.evidence_zh if volume else "没有成交量数据——不猜量价关系，也不编造成交量"
        en = (volume.evidence_en if volume else
              "No volume data — the volume-price relationship is unknown, and no "
              "volume figure is fabricated")
        return Check("volume", _VOLUME_Q_ZH, _VOLUME_Q_EN, CheckStatus.UNKNOWN, zh, en)

    if volume.blocks_act:
        return Check("volume", _VOLUME_Q_ZH, _VOLUME_Q_EN, CheckStatus.FAIL,
                     f"量价危险——{volume.evidence_zh}。书中：量增价滞是派发的信号",
                     f"Dangerous volume — {volume.evidence_en}. The book: heavy "
                     "volume with no price progress is distribution")

    if volume.confirms:
        return Check("volume", _VOLUME_Q_ZH, _VOLUME_Q_EN, CheckStatus.PASS,
                     f"量价配合——{volume.evidence_zh}。书中：涨势需要成交量的确认",
                     f"Volume confirms — {volume.evidence_en}. The book: an advance "
                     "needs volume behind it")

    return Check("volume", _VOLUME_Q_ZH, _VOLUME_Q_EN, CheckStatus.WARN,
                 f"量价不配合——{volume.evidence_zh}。书中：没有成交量的突破并没有很大意义",
                 f"Volume does not confirm — {volume.evidence_en}. The book: a "
                 "breakout without volume does not mean much")


_EDGE_Q_ZH = "有经真实数据验证的优势吗？"
_EDGE_Q_EN = "Is there a gate-approved edge on THIS instrument?"


def _edge_check(symbol: str, edges: list[EdgeInstance]) -> Check:
    """Does an approved edge actually fire on this instrument right now?

    The old version answered "does this asset class contain an approved edge?",
    which passes on every US ticker because one of them had insider buying. An
    event edge that is not firing here is not an edge here.
    """
    active = [e for e in edges if e.status is EdgeStatus.ACTIVE]
    if active:
        return Check(
            "edge", _EDGE_Q_ZH, _EDGE_Q_EN, CheckStatus.PASS,
            "；".join(e.evidence_zh for e in active),
            "; ".join(e.evidence_en for e in active),
        )

    inactive = [e for e in edges if e.status is EdgeStatus.INACTIVE]
    unknown = [e for e in edges if e.status is EdgeStatus.UNKNOWN]
    if inactive and not unknown:
        return Check(
            "edge", _EDGE_Q_ZH, _EDGE_Q_EN, CheckStatus.FAIL,
            f"{symbol} 上没有任何已验证的优势正在触发。" + "；".join(e.evidence_zh for e in inactive),
            f"No validated edge is firing on {symbol}. "
            + "; ".join(e.evidence_en for e in inactive),
        )
    if unknown:
        return Check(
            "edge", _EDGE_Q_ZH, _EDGE_Q_EN, CheckStatus.UNKNOWN,
            "无法确认该标的上是否有优势触发：" + "；".join(e.evidence_zh for e in unknown),
            f"Could not determine whether an edge applies to {symbol}: "
            + "; ".join(e.evidence_en for e in unknown),
        )
    return Check(
        "edge", _EDGE_Q_ZH, _EDGE_Q_EN, CheckStatus.FAIL,
        f"该市场没有任何通过门禁的优势可用于 {symbol}——技术信号只是观察，不是优势",
        f"No gate-approved edge is available for {symbol} — signals are "
        "observations, not an edge",
    )


_RISK_Q_ZH = "风险定义了吗？有止损位？"
_RISK_Q_EN = "Is the risk defined? Is there a stop?"
# A stop inside ordinary daily noise is not a stop, it is a guarantee of being
# shaken out. Two daily sigma is the conventional "outside normal movement"
# threshold, and it scales with the instrument instead of applying one number to
# a utility stock and a 120%-vol altcoin alike.
MIN_STOP_SIGMA = 2.0
MAX_STOP_PCT = 0.20


def _risk_check(actionable: list[dict[str, Any]], daily_vol: float | None) -> Check:
    """A stop is required for any position, not only for a purchase.

    ``actionable`` covers both directions: a short without a stop is exactly as
    undefined as a long without one, and the check used to look only at buys —
    so the short leg's risk was permanently ``UNKNOWN``.
    """
    stops = [s.get("stop_pct") for s in actionable if s.get("stop_pct") is not None]
    if not actionable:
        return Check("risk", _RISK_Q_ZH, _RISK_Q_EN, CheckStatus.UNKNOWN,
                     "当前无可执行信号，无需定义止损",
                     "No actionable signal right now, so no stop is required")
    if not stops:
        return Check("risk", _RISK_Q_ZH, _RISK_Q_EN, CheckStatus.FAIL,
                     "有可执行信号但没有止损位——书中：不定止损就不要入场",
                     "Actionable signal without a stop — the book: never enter without one")

    widest = max(float(s) for s in stops)
    if widest > MAX_STOP_PCT:
        return Check("risk", _RISK_Q_ZH, _RISK_Q_EN, CheckStatus.FAIL,
                     f"止损幅度 {widest:.0%} 超过 20% 上限",
                     f"Stop of {widest:.0%} exceeds the 20% ceiling")

    if daily_vol is None or daily_vol <= 0:
        return Check("risk", _RISK_Q_ZH, _RISK_Q_EN, CheckStatus.UNKNOWN,
                     f"止损已定 {widest:.1%}，但缺少该标的波动率，无法判断这个幅度"
                     "是否在日常噪音之内",
                     f"Stop set at {widest:.1%}, but without this instrument's "
                     "volatility there is no way to tell whether it sits inside "
                     "ordinary daily noise")

    floor = MIN_STOP_SIGMA * daily_vol
    if widest < floor:
        return Check("risk", _RISK_Q_ZH, _RISK_Q_EN, CheckStatus.FAIL,
                     f"止损 {widest:.1%} 小于该标的日波动的 {MIN_STOP_SIGMA:.0f} 倍"
                     f"（{floor:.1%}）——这不是止损，是必然被日常波动扫掉",
                     f"A {widest:.1%} stop is inside {MIN_STOP_SIGMA:.0f}× this "
                     f"instrument's daily volatility ({floor:.1%}) — normal noise "
                     "will take it out")
    return Check("risk", _RISK_Q_ZH, _RISK_Q_EN, CheckStatus.PASS,
                 f"止损已定 {widest:.1%}，为该标的日波动（{daily_vol:.1%}）的 "
                 f"{widest / daily_vol:.1f} 倍，且在 20% 上限内",
                 f"Stop at {widest:.1%} — {widest / daily_vol:.1f}× this "
                 f"instrument's daily volatility ({daily_vol:.1%}) and inside the "
                 "20% ceiling")


_TRAP_Q_ZH = "是否在犯已知的错？"
_TRAP_Q_EN = "Am I making a known mistake?"


def statuses_trap_unresolved(check: Check) -> bool:
    """True when a trap *exists* for this market but was not established clear."""
    return check.status is not CheckStatus.PASS


def _trap_check(
    domain: str, trap: EdgeInstance | None, direction: Direction = Direction.LONG
) -> Check:
    """Report the measured trap only when it was actually checked.

    Previously this returned PASS whenever no trap flag was set — including for
    every A-share, where the dragon-tiger list was never fetched at all. "I did
    not look" was being printed as "I looked and it is clear".
    """
    known = KNOWN_TRAPS.get(domain)
    if trap is None:
        detail_zh = (f"未检查该市场的实测陷阱（{known['name_zh']}）——没查过不等于没问题"
                     if known else "该市场暂无实测陷阱记录")
        detail_en = (f"This market's measured trap ({known['name_en']}) was not "
                     "checked — not looking is not the same as being clear"
                     if known else "No measured traps recorded for this market")
        return Check("known_mistake", _TRAP_Q_ZH, _TRAP_Q_EN, CheckStatus.UNKNOWN,
                     detail_zh, detail_en)

    name_zh = known["name_zh"] if known else trap.strategy
    name_en = known["name_en"] if known else trap.strategy
    blocks = known.get("blocks", Direction.LONG) if known else Direction.LONG

    if trap.status is EdgeStatus.ACTIVE and blocks is not direction:
        # The trap fired, but it is a trap for the other side. Reported, not
        # counted against us — this is the same evidence as the short edge.
        return Check("known_mistake", _TRAP_Q_ZH, _TRAP_Q_EN, CheckStatus.PASS,
                     f"该陷阱（{name_zh}）针对的是买入方向，与本次{_side_zh(direction)}相反，"
                     f"不构成阻碍：{trap.evidence_zh}",
                     f"This trap ({name_en}) applies to buying, the opposite of the side "
                     f"being taken, so it does not stand in the way: {trap.evidence_en}")

    if trap.status is EdgeStatus.ACTIVE:
        evidence_zh, evidence_en = trap_evidence(domain)
        return Check("known_mistake", _TRAP_Q_ZH, _TRAP_Q_EN, CheckStatus.FAIL,
                     f"是——{name_zh}。{trap.evidence_zh}"
                     + (f"（{evidence_zh}）" if evidence_zh else ""),
                     f"Yes — {name_en}. {trap.evidence_en}"
                     + (f" ({evidence_en})" if evidence_en else ""))
    if trap.status is EdgeStatus.UNKNOWN:
        return Check("known_mistake", _TRAP_Q_ZH, _TRAP_Q_EN, CheckStatus.UNKNOWN,
                     f"无法确认是否在犯这个错（{name_zh}）：{trap.evidence_zh}",
                     f"Could not confirm whether this mistake ({name_en}) applies: "
                     f"{trap.evidence_en}")
    return Check("known_mistake", _TRAP_Q_ZH, _TRAP_Q_EN, CheckStatus.PASS,
                 f"已在本标的上检查，未触发（{name_zh}）：{trap.evidence_zh}",
                 f"Checked on this instrument and not triggered ({name_en}): "
                 f"{trap.evidence_en}")


def judge(
    *,
    symbol: str,
    domain: str,
    data_source: str | None = None,
    as_of: str | None = None,
    bars: int = 0,
    edges: list[EdgeInstance] | None = None,
    signals: list[dict[str, Any]] | None = None,
    trap: EdgeInstance | None = None,
    trend: TrendState | None = None,
    volume: VolumeState | None = None,
    daily_vol: float | None = None,
    now: datetime | None = None,
) -> VerdictReport:
    """Run the seven checks and return an honest verdict with its evidence.

    ``trend`` is a :class:`libs.quant.trend_state.TrendState` from
    :func:`libs.quant.trend_state.classify_trend`. Passing ``None`` (or an
    ``unknown`` state) yields ``CheckStatus.UNKNOWN`` for the trend check, which
    is *not* a pass: ACT requires a confirmed uptrend, because the book's rule
    is a prohibition, and an unverified prohibition must be treated as binding.

    ``volume`` is a :class:`libs.quant.volume_state.VolumeState` from
    :func:`libs.quant.volume_state.classify_volume`, and is treated the same
    way: unmeasured participation cannot support ACT, and the two distribution
    states block it outright. Price and volume are one observation — a rally
    nobody is trading is not the same event as a rally everybody is.

    ``edges`` are :class:`libs.quant.edge_instance.EdgeInstance` results for
    **this** instrument, not a list of edges that exist somewhere in its asset
    class. Only an ``ACTIVE`` one can support ACT: the approved US edge fires on
    a ticker in the days after insiders file, and on any other ticker there is no
    edge to speak of.

    ``trap`` is the same idea for the measured mistakes, and ``None`` means the
    check could not be run — reported as ``UNKNOWN``, never as a clean pass.

    ``daily_vol`` is the instrument's daily return standard deviation, used to
    judge whether a stop is wide enough to survive ordinary noise on *this*
    instrument rather than merely below a fixed ceiling.
    """
    signals = signals or []
    edges = edges or []
    checks: list[Check] = []

    # Which way would we be acting? A firing edge names its own direction (the
    # board's ``implementation`` decides it); otherwise fall back to whatever the
    # technical signals suggest. Everything downstream — the trend check, the
    # headline, the stop semantics — is read from this seat.
    firing = [e for e in edges if e.status is EdgeStatus.ACTIVE and e.is_tradable]
    if firing:
        direction = firing[0].direction or Direction.LONG
    elif any(s.get("direction") == "short" for s in signals):
        direction = Direction.SHORT
    else:
        direction = Direction.LONG

    # 1) 看得懂吗 — real, fresh, attributed data. Staleness is per-market: an
    # altcoin bar from three days ago is old, an A-share bar from three days ago
    # may just be a weekend.
    age = _stale_days(as_of, now)
    stale_limit = STALE_LIMIT_DAYS.get(domain, DEFAULT_STALE_LIMIT_DAYS)
    if not data_source or bars <= 0:
        checks.append(Check(
            "data", "看得懂吗？数据真实且新鲜？", "Do I see it? Is the data real and fresh?",
            CheckStatus.FAIL, "没有真实数据——任何结论都是猜测",
            "No real data — any conclusion here would be a guess",
        ))
    elif age is not None and age > stale_limit:
        # Not a warning: a conclusion drawn on data this old is not a statement
        # about now, and the whole point of this check is freshness.
        checks.append(Check(
            "data", "看得懂吗？数据真实且新鲜？", "Do I see it? Is the data real and fresh?",
            CheckStatus.FAIL,
            f"数据来自 {data_source}，但已 {age} 天未更新（{domain} 上限 {stale_limit} 天）"
            "——这不是关于“现在”的判断",
            f"Data from {data_source} is {age} days stale (limit {stale_limit} for "
            f"{domain}) — this is not a judgement about the present",
        ))
    else:
        checks.append(Check(
            "data", "看得懂吗？数据真实且新鲜？", "Do I see it? Is the data real and fresh?",
            CheckStatus.PASS, f"{bars} 根真实K线，来源 {data_source}，截至 {as_of}",
            f"{bars} real bars from {data_source}, as of {as_of}",
        ))

    # 2) 有验证过的优势吗 — and does it apply to THIS instrument, right now?
    checks.append(_edge_check(symbol, edges))

    # 3) 风险定义了吗 — a stop must exist, fit the book's ceiling, and be wider
    # than this instrument's ordinary daily noise.
    wanted_side = "short" if direction is Direction.SHORT else "buy"
    actionable = [s for s in signals if s.get("direction") == wanted_side]
    # A firing edge is itself an actionable instruction even when the technical
    # signal layer has nothing to say: the edge *is* the entry rule, measured.
    has_action = bool(actionable) or bool(firing)
    checks.append(_risk_check(actionable, daily_vol))

    # 4) 是否在犯已知的错 — the measured traps, actually checked on this symbol.
    checks.append(_trap_check(domain, trap, direction))
    # "This market has no measured trap" and "this market has one and I could not
    # check it" are both UNKNOWN, but only the second is a reason to hold back.
    # Treating them alike made every US stock unreachable for ACT, because no
    # trap has ever been measured for US equities.
    trap_unresolved = (
        domain in KNOWN_TRAPS and statuses_trap_unresolved(checks[-1])
    )

    # 5) 顺势还是逆势 — the book's directional prohibition, read for our side.
    checks.append(_trend_check(trend, direction))

    # 6) 量价配合吗 — direction without participation is half an observation.
    checks.append(_volume_check(volume))

    # 7) 结论 — conservative by construction.
    statuses = {c.key: c.status for c in checks}
    if statuses["known_mistake"] is CheckStatus.FAIL:
        verdict = Verdict.AVOID
        zh = "回避——你正在犯一个已被真实数据证实的错误"
        en = "Avoid — you are making a mistake this project measured on real data"
    elif statuses["data"] is CheckStatus.FAIL:
        verdict = Verdict.WAIT
        zh = "等待——没有可信数据就没有判断，别把猜测当结论"
        en = "Wait — without trustworthy data there is no judgement, only a guess"
    elif statuses["trend"] is CheckStatus.FAIL:
        # "绝不要在跌势时入市", and its mirror for a short. With a position in
        # mind this is an active mistake to avoid; with nothing to act on there
        # is simply nothing to do.
        verdict = Verdict.AVOID if has_action else Verdict.WAIT
        against = "跌势" if direction is Direction.LONG else "升势"
        zh = (f"回避——标的处于{against}，与你要做的方向相反。书中：绝不要逆势入市"
              if has_action else f"等待——标的处于{against}，不是{_side_zh(direction)}的时候")
        en = ("Avoid — the trend runs against the side you would be taking. "
              "The book: never enter against it" if has_action else
              "Wait — the trend runs against that side; not a time to enter")
    elif statuses["volume"] is CheckStatus.FAIL and not firing:
        # 量增价滞 / 成交量高潮 — the book's two distribution patterns.
        #
        # Deliberately skipped when a validated edge is firing. Those edges were
        # measured as standalone event studies: the altcoin short's +3.20% over
        # 234 events was recorded with no volume condition attached. Layering an
        # unvalidated filter on top is not extra caution — it silently trades a
        # different strategy from the one the evidence describes, and the book's
        # volume doctrine is written for buying anyway.
        verdict = Verdict.AVOID if has_action else Verdict.WAIT
        zh = ("回避——量价形态是派发或衰竭。书中：量增价滞是见顶的信号" if has_action
              else "等待——量价形态是派发或衰竭，不是入市的时候")
        en = ("Avoid — the volume pattern is distribution or exhaustion. The book: "
              "heavy volume with no price progress marks a top" if has_action else
              "Wait — the volume pattern is distribution or exhaustion; not a time to enter")
    elif statuses["risk"] is CheckStatus.FAIL:
        verdict = Verdict.WAIT
        zh = "等待——风险未定义。书中：选买点最重要的是选择止损点"
        en = "Wait — risk undefined. The book: choosing the stop matters most"
    elif (firing
          and statuses["data"] is CheckStatus.PASS
          and not trap_unresolved
          and statuses["risk"] is not CheckStatus.FAIL
          and statuses["trend"] is not CheckStatus.FAIL):
        # A validated edge is firing on this instrument. The gates that bind here
        # are the ones the edge's own study honoured — fresh data, the measured
        # traps, a defined stop, and not trading straight into the opposing
        # trend. The book's volume confirmation is *not* among them, for the
        # reason given above.
        verdict = Verdict.ACT
        side = _side_zh(direction)
        zh = (f"可以{side}——{_edge_names(firing)} 正在本标的上触发，"
              "数据新鲜、已核对实测陷阱、风险已定义")
        en = (f"Act ({direction.value}) — {_edge_names_en(firing)} is firing on this "
              "instrument; data is fresh, the measured traps were checked, and risk "
              "is defined")
    elif (statuses["edge"] is CheckStatus.PASS and actionable
          and statuses["data"] is CheckStatus.PASS
          and not trap_unresolved
          and statuses["risk"] is CheckStatus.PASS
          and statuses["trend"] is CheckStatus.PASS
          and statuses["volume"] is CheckStatus.PASS):
        verdict = Verdict.ACT
        side = _side_zh(direction)
        zh = (f"可以{side}——数据新鲜、该标的上有正在触发的已验证优势、已核对过实测陷阱、"
              "风险已定义、顺势而为、且量价配合")
        en = ("Act — data is fresh, a validated edge is firing on this instrument, "
              "the measured traps were checked, risk is defined, it is with the "
              "trend, and volume confirms it")
    elif actionable and statuses["edge"] is CheckStatus.PASS and statuses["trend"] is not CheckStatus.PASS:
        verdict = Verdict.WATCH
        zh = "观察——优势与风险都在位，但趋势没有站在你这边，等趋势确认"
        en = "Watch — edge and risk are in place, but the trend is not confirmed; wait for it"
    elif actionable and statuses["edge"] is CheckStatus.PASS and statuses["volume"] is not CheckStatus.PASS:
        verdict = Verdict.WATCH
        zh = "观察——顺势且风险已定，但成交量没有确认，等放量"
        en = ("Watch — with the trend and risk defined, but volume does not confirm "
              "the move; wait for participation")
    elif has_action and trap_unresolved:
        # Something to act on while the market's measured trap was never checked.
        # The honest answer is that the most important question was not asked.
        verdict = Verdict.WATCH
        zh = "观察——有可执行信号，但本市场实测过的陷阱没能核对，不能当作没问题"
        en = ("Watch — an actionable signal, but this market's measured trap could "
              "not be checked, which is not the same as it being clear")
    elif has_action:
        verdict = Verdict.WATCH
        zh = "观察——有技术信号，但该标的上没有正在触发的、经真实数据验证的优势"
        en = ("Watch — a technical signal, but no validated edge is firing on this "
              "instrument")
    else:
        verdict = Verdict.WAIT
        zh = "等待——当前没有值得行动的理由。大多数时候，什么都不做才是对的"
        en = "Wait — no reason to act. Most of the time, doing nothing is correct"

    return VerdictReport(symbol=symbol, domain=domain, verdict=verdict,
                         headline_zh=zh, headline_en=en, checks=checks)


__all__ = ["MAX_STOP_PCT", "MIN_STOP_SIGMA", "STALE_LIMIT_DAYS", "Check",
           "CheckStatus", "EdgeInstance", "EdgeStatus", "KNOWN_TRAPS",
           "TrendState", "Verdict", "VerdictReport", "VolumeState", "judge",
           "trap_evidence"]
