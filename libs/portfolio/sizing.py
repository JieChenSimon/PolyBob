"""How much to buy — derived from the measured edge and the real account.

Kelly and its estimation-error variant sat in ``libs/quant/position_sizing.py``
with zero callers for the whole life of the project, while the number the product
actually printed came from ``capital / 10`` on a hardcoded 100,000. The maths was
never the problem; there was no account to size against and no measured edge to
size from.

Both now exist, so this module wires them together — with three corrections that
matter more than the formula itself:

**Estimation error goes into the input, not onto the output.** Kelly maximises
growth when the win rate is *known*. Ours is estimated, and its failure mode under
an optimistic input is ruin rather than underperformance — the loss function is
brutally asymmetric. The first version of this module multiplied Kelly's *answer*
by ``sqrt(n/20)``, and the archived ``position_sizing.kelly_with_estimation_error``
did the same thing with ``1/(1+variance)``. Both are the wrong layer: they shrink a
number computed from a win rate nobody should have trusted at face value.

The correction belongs on the win rate itself. We bet the **lower confidence bound**
— the pessimistic end of what the sample actually supports — using the Wilson score
interval, which is the standard treatment for a binomial proportion at small n and
behaves properly near 0 and 1 where the normal approximation does not.

The difference is not cosmetic. On the US insider edge (53.2% over 9 independent
months) the multiplicative version produced 10%; the confidence bound produces
**2.2%**, because a 53.2% win rate measured over nine months could comfortably be
37%, and at 37% with a 1.8:1 payoff there is barely an edge to bet. The altcoin edge
(70.6% over 13 weeks) still sizes at the cap. Two edges that used to receive
identical fractions now differ by more than four times, and the thing driving the
difference is how much evidence each one has.

It also converges the right way: hold the win rate fixed and grow the sample, and
the fraction climbs from 2.2% at n=9 towards Kelly's 27% at n=200. Sizing gets
bigger by *earning* it.

**The cap.** Even so, Kelly on a 70% win rate suggests a third of the account. No
estimate from 13 weeks justifies that, so
:data:`~libs.portfolio.account.MAX_POSITION_FRACTION` binds and the book's "capital
in ten parts" and the maths meet at the same place.

**The budget.** Sizing asks the account what room is left, so two edges cannot
each take their "safe" tenth in the same direction.

Every function returns ``None`` for the amount when the account is unconfigured,
and still returns the *fraction*, because the rule is knowable without an account
and the money is not.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from libs.portfolio.account import (
    MAX_DOMAIN_FRACTION,
    MAX_POSITION_FRACTION,
    MAX_TOTAL_RISK_FRACTION,
    Account,
)


@dataclass(frozen=True)
class EdgeStatistics:
    """What the board measured, in the form sizing needs.

    ``n_clusters`` — not ``n`` — is the sample size that governs how much to trust
    the win rate, for the same reason it governs the t-statistic: 245 events inside
    13 weeks is thirteen observations of the market wearing a large-n disguise.
    """

    win_rate: float
    mean_excess: float             # as a fraction, e.g. 0.0511
    n_clusters: int
    win_loss_ratio: float | None = None

    @property
    def payoff_ratio(self) -> float:
        """Average win over average loss.

        Falls back to 1.0 when unmeasured. That is the conservative choice: a 1:1
        payoff needs a win rate above 50% to have any Kelly fraction at all, so an
        unknown payoff cannot flatter the size.
        """
        if self.win_loss_ratio and self.win_loss_ratio > 0:
            return float(self.win_loss_ratio)
        return 1.0


def kelly_fraction(stats: EdgeStatistics) -> float:
    """Textbook Kelly: ``(p*b - q) / b``. Never negative.

    A negative Kelly means the edge loses money, and the answer to that is not a
    short — the direction was pre-registered — it is no position.
    """
    p = max(0.0, min(1.0, stats.win_rate))
    b = stats.payoff_ratio
    if b <= 0:
        return 0.0
    return max(0.0, (p * b - (1.0 - p)) / b)


# How pessimistic to be about the win rate, in standard errors. One sigma is a
# judgement, not a derivation, and it is stated here rather than buried so that
# changing it is a visible decision. The reasoning: Kelly's downside from
# over-betting is unbounded and its downside from under-betting is merely slower
# growth, so the asymmetry argues for at least one sigma. Two would be defensible;
# zero — betting the point estimate — is what ruins accounts.
WIN_RATE_CONFIDENCE_SIGMA = 1.0


def win_rate_lower_bound(
    win_rate: float, n_clusters: int, *, sigma: float = WIN_RATE_CONFIDENCE_SIGMA
) -> float:
    """The pessimistic end of the win rate, by the Wilson score interval.

    Wilson rather than the textbook ``p ± z*sqrt(p(1-p)/n)`` because that normal
    approximation misbehaves exactly where this project lives: small n, and rates
    far from 50%. Wilson stays inside [0, 1] and does not collapse to a zero-width
    interval when every observation wins.

    ``n_clusters``, never ``n``. 245 events inside 13 weeks is thirteen observations
    of the market wearing a large-n disguise, and the standard error must be built
    from the count that is actually independent — the same reason the t-statistic
    is clustered.
    """
    if n_clusters <= 0:
        return 0.0
    p = max(0.0, min(1.0, win_rate))
    z = sigma
    denominator = 1.0 + z * z / n_clusters
    centre = (p + z * z / (2 * n_clusters)) / denominator
    margin = (z / denominator) * math.sqrt(
        p * (1.0 - p) / n_clusters + z * z / (4.0 * n_clusters * n_clusters)
    )
    return max(0.0, centre - margin)


@dataclass(frozen=True)
class SizeDecision:
    """The answer, with every step of the reasoning attached.

    The steps are not decoration. "Buy 340 shares" is unauditable; "the measured
    53.2% win rate gives Kelly 27%, but over 9 independent months its 1-sigma lower
    bound is 37% and Kelly there is 2.2%, and the domain budget had room" can be
    argued with — and a number you can argue with is the only kind worth acting on.
    """

    fraction: float                  # of equity, after every constraint
    amount: float | None             # None when the account is unconfigured
    shares: float | None
    kelly_point: float               # Kelly on the measured win rate — the optimistic read
    kelly_prudent: float             # Kelly on the lower confidence bound — what we bet
    win_rate_used: float             # the pessimistic win rate the size rests on
    binding_constraint: str
    reasons_zh: list[str]
    allowed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "fraction": round(self.fraction, 5),
            "amount": None if self.amount is None else round(self.amount, 2),
            "shares": None if self.shares is None else math.floor(self.shares),
            # Both Kellys are reported. The gap between them *is* the evidence
            # quality, and hiding the optimistic one hides how much of the
            # difference between two edges comes from sample length rather than
            # from the edges themselves.
            "kelly_point": round(self.kelly_point, 5),
            "kelly_prudent": round(self.kelly_prudent, 5),
            "win_rate_used": round(self.win_rate_used, 4),
            "binding_constraint": self.binding_constraint,
            "reasons_zh": list(self.reasons_zh),
            "capital_known": self.amount is not None,
        }


def size_position(
    stats: EdgeStatistics,
    account: Account,
    *,
    domain: str,
    entry_price: float | None = None,
    stop_price: float | None = None,
) -> SizeDecision:
    """The fraction of equity this edge may take right now, and why that much."""
    reasons: list[str] = []
    point = kelly_fraction(stats)
    prudent_win_rate = win_rate_lower_bound(stats.win_rate, stats.n_clusters)
    prudent = kelly_fraction(EdgeStatistics(
        win_rate=prudent_win_rate, mean_excess=stats.mean_excess,
        n_clusters=stats.n_clusters, win_loss_ratio=stats.win_loss_ratio,
    ))
    fraction = prudent
    binding = "kelly_on_lower_bound"

    reasons.append(
        f"实测胜率 {stats.win_rate*100:.1f}%,盈亏比 {stats.payoff_ratio:.2f} "
        f"→ 点估计 Kelly {point*100:.1f}%"
    )
    reasons.append(
        f"但这个胜率只建立在 {stats.n_clusters} 个独立单元上,"
        f"{WIN_RATE_CONFIDENCE_SIGMA:.0f}σ 置信下界是 {prudent_win_rate*100:.1f}% "
        f"→ 按下界下注 Kelly {prudent*100:.2f}%"
    )

    def _decision(frac: float, why: str, extra: list[str], ok: bool) -> SizeDecision:
        amount = frac * account.equity if account.configured else None    # type: ignore[operator]
        return SizeDecision(
            frac, amount, None, point, prudent, prudent_win_rate, why,
            reasons + extra, ok,
        )

    if point <= 0:
        return _decision(0.0, "negative_edge",
                         ["点估计 Kelly ≤ 0 —— 这条边不赚钱,不开仓。"], False)
    if prudent <= 0:
        return _decision(
            0.0, "no_edge_at_lower_bound",
            [f"按 {prudent_win_rate*100:.1f}% 的下界算已经没有优势了 —— "
             f"这条边可能是真的,但样本还不足以让人下注。延长样本期,不是放宽标准。"],
            False,
        )

    if fraction > MAX_POSITION_FRACTION:
        fraction = MAX_POSITION_FRACTION
        binding = "max_position_cap"
        reasons.append(
            f"单笔上限 {MAX_POSITION_FRACTION*100:.0f}% 生效 —— "
            f"即使按下界,Kelly 仍然大于任何单笔该承受的比例。"
        )

    # Budgets need real money to be checked against.
    if not account.configured:
        reasons.append("账户权益未配置:只给比例,不给金额和股数。")
        return SizeDecision(fraction, None, None, point, prudent,
                            prudent_win_rate, binding, reasons, True)

    equity = account.require_equity()

    used = account.domain_notional(domain)
    room = max(0.0, MAX_DOMAIN_FRACTION * equity - used)
    if fraction * equity > room:
        fraction = room / equity
        binding = "domain_budget"
        reasons.append(
            f"{domain} 已占用 {used/equity*100:.1f}%,域上限 "
            f"{MAX_DOMAIN_FRACTION*100:.0f}% —— 只剩 {fraction*100:.1f}%。"
        )

    # The risk budget uses correlated risk, so an altcoin short and a US long are
    # not treated as offsetting.
    current_risk = account.correlated_risk()
    risk_room = max(0.0, MAX_TOTAL_RISK_FRACTION * equity - current_risk)
    if stop_price is not None and entry_price and entry_price > 0:
        risk_per_unit = abs(entry_price - stop_price) / entry_price
        if risk_per_unit > 0:
            max_by_risk = risk_room / risk_per_unit
            if fraction * equity > max_by_risk:
                fraction = max(0.0, max_by_risk / equity)
                binding = "total_risk_budget"
                reasons.append(
                    f"全账户相关性风险已占 {current_risk/equity*100:.2f}%,上限 "
                    f"{MAX_TOTAL_RISK_FRACTION*100:.0f}% —— 按止损距离 "
                    f"{risk_per_unit*100:.1f}% 回算,仓位降到 {fraction*100:.1f}%。"
                )
    elif stop_price is None:
        reasons.append("没有止损价:风险预算无法核算,这笔按未定义风险处理。")

    amount = fraction * equity
    shares = (amount / entry_price) if entry_price and entry_price > 0 else None
    allowed = fraction > 0
    if not allowed:
        reasons.append("可用额度为 0 —— 先减仓或提高权益,再考虑这条边。")
    return SizeDecision(fraction, amount, shares, point, prudent,
                        prudent_win_rate, binding, reasons, allowed)


__all__ = [
    "WIN_RATE_CONFIDENCE_SIGMA", "EdgeStatistics", "SizeDecision",
    "kelly_fraction", "size_position", "win_rate_lower_bound",
]
