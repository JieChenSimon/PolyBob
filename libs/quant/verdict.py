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

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

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


# Traps this project measured on real data — not opinions, findings.
KNOWN_TRAPS: dict[str, dict[str, Any]] = {
    "a_share": {
        "name_zh": "龙虎榜上榜后追高",
        "name_en": "buying a fresh dragon-tiger listing",
        "evidence_zh": "44,750 个真实事件：一周平均跑输大盘 1.83%，64% 跑输",
        "evidence_en": "44,750 real events: -1.83% vs market over a week, 64% underperform",
    },
    "altcoin": {
        "name_zh": "散户极度做多时买入",
        "name_en": "buying when retail is crowded long",
        "evidence_zh": "343 个样本：一周平均 -2.04%，胜率仅 38.8%",
        "evidence_en": "343 samples: -2.04% over a week, win rate 38.8%",
    },
}


def _stale_days(as_of: str | None, now: datetime | None = None) -> int | None:
    if not as_of:
        return None
    try:
        seen = datetime.fromisoformat(as_of[:10]).replace(tzinfo=UTC)
    except ValueError:
        return None
    return (( now or datetime.now(UTC)) - seen).days


_TREND_Q_ZH = "顺势还是逆势？"
_TREND_Q_EN = "With or against the trend?"


def _trend_check(trend: TrendState | None) -> Check:
    """Map a trend state onto the check semantics.

    ``PASS`` only for a confirmed up-trend, ``FAIL`` for either downtrend grade,
    ``WARN`` for a directionless market (a signal there is a coin flip, not an
    edge), and ``UNKNOWN`` when history is too short to say — never a silent
    ``PASS``, because "I could not measure it" and "it is fine" are different
    claims and confusing them is exactly the error the book warns about.
    """
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


def judge(
    *,
    symbol: str,
    domain: str,
    data_source: str | None = None,
    as_of: str | None = None,
    bars: int = 0,
    promoted_edges: list[str] | None = None,
    signals: list[dict[str, Any]] | None = None,
    trap_flags: dict[str, bool] | None = None,
    trend: TrendState | None = None,
    volume: VolumeState | None = None,
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
    """
    signals = signals or []
    promoted_edges = promoted_edges or []
    trap_flags = trap_flags or {}
    checks: list[Check] = []

    # 1) 看得懂吗 — real, fresh, attributed data.
    age = _stale_days(as_of, now)
    if not data_source or bars <= 0:
        checks.append(Check(
            "data", "看得懂吗？数据真实且新鲜？", "Do I see it? Is the data real and fresh?",
            CheckStatus.FAIL, "没有真实数据——任何结论都是猜测",
            "No real data — any conclusion here would be a guess",
        ))
    elif age is not None and age > 5:
        checks.append(Check(
            "data", "看得懂吗？数据真实且新鲜？", "Do I see it? Is the data real and fresh?",
            CheckStatus.WARN, f"数据来自 {data_source}，但已 {age} 天未更新",
            f"Data from {data_source} but {age} days stale",
        ))
    else:
        checks.append(Check(
            "data", "看得懂吗？数据真实且新鲜？", "Do I see it? Is the data real and fresh?",
            CheckStatus.PASS, f"{bars} 根真实K线，来源 {data_source}，截至 {as_of}",
            f"{bars} real bars from {data_source}, as of {as_of}",
        ))

    # 2) 有验证过的优势吗 — gate-approved, not merely plausible.
    if promoted_edges:
        checks.append(Check(
            "edge", "有经真实数据验证的优势吗？", "Is there a gate-approved edge?",
            CheckStatus.PASS, f"该市场已有通过门禁的优势：{'、'.join(promoted_edges)}",
            f"Gate-approved edge(s) for this market: {', '.join(promoted_edges)}",
        ))
    else:
        checks.append(Check(
            "edge", "有经真实数据验证的优势吗？", "Is there a gate-approved edge?",
            CheckStatus.FAIL, "该市场没有任何通过门禁的优势——技术信号只是观察，不是优势",
            "No gate-approved edge for this market — signals are observations, not an edge",
        ))

    # 3) 风险定义了吗 — a stop must exist before entry.
    buys = [s for s in signals if s.get("direction") == "buy"]
    stops = [s.get("stop_pct") for s in buys if s.get("stop_pct") is not None]
    if not buys:
        checks.append(Check(
            "risk", "风险定义了吗？有止损位？", "Is the risk defined? Is there a stop?",
            CheckStatus.UNKNOWN, "当前无买入信号，无需定义止损",
            "No buy signal right now, so no stop is required",
        ))
    elif not stops:
        checks.append(Check(
            "risk", "风险定义了吗？有止损位？", "Is the risk defined? Is there a stop?",
            CheckStatus.FAIL, "有买入信号但没有止损位——书中：不定止损就不要入场",
            "Buy signal without a stop — the book: never enter without one",
        ))
    elif max(stops) > 0.20:
        checks.append(Check(
            "risk", "风险定义了吗？有止损位？", "Is the risk defined? Is there a stop?",
            CheckStatus.FAIL, f"止损幅度 {max(stops):.0%} 超过 20% 上限",
            f"Stop of {max(stops):.0%} exceeds the 20% ceiling",
        ))
    else:
        checks.append(Check(
            "risk", "风险定义了吗？有止损位？", "Is the risk defined? Is there a stop?",
            CheckStatus.PASS, f"止损已定，最大风险 {max(stops):.1%}",
            f"Stop defined, max risk {max(stops):.1%}",
        ))

    # 4) 是否在犯已知的错 — the measured traps.
    active_traps = [k for k, v in trap_flags.items() if v]
    if active_traps:
        trap = KNOWN_TRAPS.get(active_traps[0], {})
        checks.append(Check(
            "known_mistake", "是否在犯已知的错？", "Am I making a known mistake?",
            CheckStatus.FAIL,
            f"是——{trap.get('name_zh', active_traps[0])}。{trap.get('evidence_zh', '')}",
            f"Yes — {trap.get('name_en', active_traps[0])}. {trap.get('evidence_en', '')}",
        ))
    else:
        trap = KNOWN_TRAPS.get(domain)
        detail_zh = f"未触发本项目实测的陷阱（{trap['name_zh']}）" if trap else "该市场暂无实测陷阱记录"
        detail_en = (f"None of this project's measured traps are active ({trap['name_en']})"
                     if trap else "No measured traps recorded for this market")
        checks.append(Check(
            "known_mistake", "是否在犯已知的错？", "Am I making a known mistake?",
            CheckStatus.PASS if trap else CheckStatus.UNKNOWN, detail_zh, detail_en,
        ))

    # 5) 顺势还是逆势 — the book's directional prohibition.
    checks.append(_trend_check(trend))

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
        # "绝不要在跌势时入市" — with a buy signal in hand this is an active
        # mistake to avoid; with no signal there is simply nothing to do.
        verdict = Verdict.AVOID if buys else Verdict.WAIT
        zh = ("回避——标的处于跌势。书中：绝不要在跌势时入市" if buys
              else "等待——标的处于跌势，不是入市的时候")
        en = ("Avoid — this instrument is in a downtrend. The book: never enter during one"
              if buys else "Wait — this instrument is in a downtrend; not a time to enter")
    elif statuses["volume"] is CheckStatus.FAIL:
        # 量增价滞 / 成交量高潮 — the book's two distribution patterns. As with the
        # trend prohibition, it is an active mistake only if you were about to buy.
        verdict = Verdict.AVOID if buys else Verdict.WAIT
        zh = ("回避——量价形态是派发或衰竭。书中：量增价滞是见顶的信号" if buys
              else "等待——量价形态是派发或衰竭，不是入市的时候")
        en = ("Avoid — the volume pattern is distribution or exhaustion. The book: "
              "heavy volume with no price progress marks a top" if buys else
              "Wait — the volume pattern is distribution or exhaustion; not a time to enter")
    elif statuses["risk"] is CheckStatus.FAIL:
        verdict = Verdict.WAIT
        zh = "等待——风险未定义。书中：选买点最重要的是选择止损点"
        en = "Wait — risk undefined. The book: choosing the stop matters most"
    elif (statuses["edge"] is CheckStatus.PASS and buys
          and statuses["risk"] is CheckStatus.PASS
          and statuses["trend"] is CheckStatus.PASS
          and statuses["volume"] is CheckStatus.PASS):
        verdict = Verdict.ACT
        zh = "可以行动——数据可信、有验证过的优势、风险已定义、顺势而为、且量价配合"
        en = ("Act — data is trustworthy, a validated edge exists, risk is defined, "
              "it is with the trend, and volume confirms it")
    elif buys and statuses["edge"] is CheckStatus.PASS and statuses["trend"] is not CheckStatus.PASS:
        verdict = Verdict.WATCH
        zh = "观察——优势与风险都在位，但趋势没有站在你这边，等升势确认"
        en = "Watch — edge and risk are in place, but the trend is not confirmed; wait for it"
    elif buys and statuses["edge"] is CheckStatus.PASS and statuses["volume"] is not CheckStatus.PASS:
        verdict = Verdict.WATCH
        zh = "观察——顺势且风险已定，但成交量没有确认这次上涨，等放量"
        en = ("Watch — with the trend and risk defined, but volume does not confirm "
              "the advance; wait for participation")
    elif buys:
        verdict = Verdict.WATCH
        zh = "观察——有技术信号，但缺少经真实数据验证的优势支撑"
        en = "Watch — a technical signal, but no validated edge behind it"
    else:
        verdict = Verdict.WAIT
        zh = "等待——当前没有值得行动的理由。大多数时候，什么都不做才是对的"
        en = "Wait — no reason to act. Most of the time, doing nothing is correct"

    return VerdictReport(symbol=symbol, domain=domain, verdict=verdict,
                         headline_zh=zh, headline_en=en, checks=checks)


__all__ = ["Check", "CheckStatus", "KNOWN_TRAPS", "TrendState", "Verdict",
           "VerdictReport", "VolumeState", "judge"]
