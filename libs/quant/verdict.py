"""投资准则判定 — the honest verdict engine.

《炒股的智慧》: "犯错并不可怕，可怕的是不知自己犯了错，知错却不肯认错就更加不可
救药。" The dangerous state is not being wrong; it is being wrong without knowing.
So this engine's job is not to predict prices — it is to answer, for one
instrument, right now: **do I actually understand this, and am I about to make a
mistake I already know about?**

Five checks, in the order the book reasons:

1. **看得懂吗 (Do I see it?)** — is the data real, fresh, and from a named source?
   A conclusion drawn on stale or missing data is a guess wearing a suit.
2. **有验证过的优势吗 (Is there a proven edge?)** — has anything for this domain
   cleared the promotion gate on real data? Unvalidated signals are opinions.
3. **风险定义了吗 (Is the risk defined?)** — is there a stop, and is it within the
   book's 20% ceiling? "选买点最重要的是选择止损点."
4. **是否在犯已知的错 (Known mistakes)** — the specific traps this project has
   *measured*: buying into a fresh dragon-tiger listing (-1.83% over 44,750
   events), buying when retail is crowded long (-2.04%), chasing a parabolic run.
5. **结论 (Verdict)** — and when the checks disagree, the answer defaults to
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
    now: datetime | None = None,
) -> VerdictReport:
    """Run the five checks and return an honest verdict with its evidence."""
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

    # 5) 结论 — conservative by construction.
    statuses = {c.key: c.status for c in checks}
    if statuses["known_mistake"] is CheckStatus.FAIL:
        verdict = Verdict.AVOID
        zh = "回避——你正在犯一个已被真实数据证实的错误"
        en = "Avoid — you are making a mistake this project measured on real data"
    elif statuses["data"] is CheckStatus.FAIL:
        verdict = Verdict.WAIT
        zh = "等待——没有可信数据就没有判断，别把猜测当结论"
        en = "Wait — without trustworthy data there is no judgement, only a guess"
    elif statuses["risk"] is CheckStatus.FAIL:
        verdict = Verdict.WAIT
        zh = "等待——风险未定义。书中：选买点最重要的是选择止损点"
        en = "Wait — risk undefined. The book: choosing the stop matters most"
    elif statuses["edge"] is CheckStatus.PASS and buys and statuses["risk"] is CheckStatus.PASS:
        verdict = Verdict.ACT
        zh = "可以行动——数据可信、有验证过的优势、风险已定义"
        en = "Act — data is trustworthy, a validated edge exists, risk is defined"
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


__all__ = ["Check", "CheckStatus", "KNOWN_TRAPS", "Verdict", "VerdictReport", "judge"]
