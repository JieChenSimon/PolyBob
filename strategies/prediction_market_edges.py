"""Prediction-market–specific systematic edges (Polymarket).

Documented inefficiencies from the prediction-market literature, implemented as
pure functions. These are *relative-value / discipline* edges rather than
directional alpha, so they are kept separate from the directional signals:

- **Intra-market Yes/No arbitrage** — if buying both YES and NO costs < 1.00,
  the payoff is a guaranteed 1.00, i.e. risk-free profit regardless of outcome.
- **Combinatorial mispricing** — a logically-nested pair must satisfy
  ``P(subset) <= P(superset)`` (e.g. "Trump wins" ⊆ "Republican wins"). A
  violation is a tradable inconsistency.
- **Favorite-longshot discipline** — cheap longshots are systematically
  overpriced (sub-10¢ YES contracts lose ~60%+ on average), so this is enforced
  as a hard sizing rule, not a standalone strategy.

Sources: Snowberg/Wolfers/Zitzewitz (favorite-longshot bias); QuantPedia
"Systematic Edges in Prediction Markets"; Polymarket arbitrage analyses.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArbitrageOpportunity:
    exists: bool
    cost: float
    profit_per_unit: float
    detail: str


def yes_no_arbitrage(yes_ask: float, no_ask: float, *, fee: float = 0.0) -> ArbitrageOpportunity:
    """Risk-free edge from buying YES+NO when their combined ask < 1.

    ``yes_ask`` / ``no_ask`` are executable prices in [0, 1]. Buying one of each
    pays out exactly 1 at resolution, so profit per unit is ``1 - (yes+no+fee)``.
    """
    cost = float(yes_ask) + float(no_ask) + float(fee)
    profit = 1.0 - cost
    exists = profit > 0
    return ArbitrageOpportunity(
        exists=exists,
        cost=cost,
        profit_per_unit=max(profit, 0.0),
        detail=(
            f"buy YES@{yes_ask:.3f}+NO@{no_ask:.3f} costs {cost:.3f} < 1 -> {profit:.3f} risk-free"
            if exists
            else f"YES+NO+fee = {cost:.3f} >= 1, no arbitrage"
        ),
    )


@dataclass(frozen=True)
class CombinatorialMispricing:
    mispriced: bool
    violation: float
    action: str | None
    detail: str


def combinatorial_mispricing(
    subset_prob: float,
    superset_prob: float,
    *,
    tol: float = 0.0,
) -> CombinatorialMispricing:
    """Detect a logical inconsistency between nested markets.

    If event A implies event B (A ⊆ B), then ``P(A) <= P(B)``. When the market
    prices violate this by more than ``tol``, sell the over-priced subset and
    buy the under-priced superset.
    """
    violation = float(subset_prob) - float(superset_prob)
    mispriced = violation > tol
    return CombinatorialMispricing(
        mispriced=mispriced,
        violation=max(violation, 0.0),
        action="sell_subset_buy_superset" if mispriced else None,
        detail=(
            f"P(subset)={subset_prob:.3f} > P(superset)={superset_prob:.3f} (violates A⊆B)"
            if mispriced
            else "nesting constraint satisfied"
        ),
    )


def favorite_longshot_ok(price: float, *, is_buy_yes: bool, floor: float = 0.10) -> bool:
    """Favorite-longshot discipline: refuse to *buy* YES longshots below ``floor``.

    Cheap longshots are systematically overpriced, so buying them is
    negative-EV on average. Selling them, or trading favorites, is unaffected.
    """
    if is_buy_yes and float(price) < floor:
        return False
    return True


def longshot_size_scale(price: float, *, is_buy_yes: bool, floor: float = 0.10, taper: float = 0.20) -> float:
    """Continuous version of the discipline: 0 below ``floor``, ramping to 1.

    Between ``floor`` and ``floor + taper`` the allowed size scales linearly, so
    positions near the longshot region are shrunk rather than hard-cut.
    """
    if not is_buy_yes:
        return 1.0
    p = float(price)
    if p < floor:
        return 0.0
    if p >= floor + taper:
        return 1.0
    return (p - floor) / taper


__all__ = [
    "ArbitrageOpportunity",
    "CombinatorialMispricing",
    "combinatorial_mispricing",
    "favorite_longshot_ok",
    "longshot_size_scale",
    "yes_no_arbitrage",
]
