"""The account: what you actually hold, and how much of it one edge may use.

Return is edge times size, and this project had no substrate for the second half.
The verdict API passed a hardcoded ``capital=100_000`` into the book's "one of ten
parts" rule, so the field telling you *how much to buy* was derived from an account
nobody owns. ``libs/quant/position_sizing.py`` held Kelly and its
estimation-error variant, and had zero callers — not because the maths was wrong
but because there was no equity, no cash and no positions for it to size against.

So this module is the missing foundation, and it has three jobs:

1. **State that is entered, not inferred.** Equity and cash come from the person
   who owns the account. There is no plausible default, and inventing one is how
   a fabricated number reached the one field that moves money.
2. **Size from the measured edge, not from a constant.** A 53.2% win rate and a
   68.4% one do not deserve the same fraction. Kelly says how much, and the
   estimation-error haircut says how much less to trust it when the sample is
   short — which, at 9 independent months, is a great deal less.
3. **A budget across edges, not per edge.** A US equity long and an altcoin short
   are not hedges: in a risk-asset selloff they lose together. Two edges each
   sized to a "safe" tenth can be a fifth of the account pointed the same way.

Nothing here grants permission to trade. That remains
:mod:`libs.quant.promotion_registry`'s job, and today it grants none.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from typing import Any

# The most any single position may take, whatever Kelly says. Kelly maximises
# long-run growth under the assumption that the win rate is *known*; ours is
# estimated from nine independent months, and Kelly's failure mode when the input
# is optimistic is ruin rather than underperformance. The book's "capital in ten
# parts" arrives at the same place from experience.
MAX_POSITION_FRACTION = 0.10

# The most any one domain may hold at once. Three simultaneous US equity longs are
# one bet on US equities.
MAX_DOMAIN_FRACTION = 0.25

# The most the account may have at risk across everything. "At risk" means the sum
# of (position size x distance to stop), not the notional: it is the number that
# answers "if every stop hits at once, what is left".
MAX_TOTAL_RISK_FRACTION = 0.06

# Correlation assumed between edges when nothing better is measured. Risk assets
# co-move in stress, and the honest default is *not* zero — zero correlation is
# the assumption that makes diversification look free.
ASSUMED_CROSS_DOMAIN_CORRELATION = 0.5


class AccountNotConfigured(RuntimeError):
    """Raised when sizing is attempted without a real account behind it."""


@dataclass(frozen=True)
class Position:
    """One open position, as recorded in the journal."""

    symbol: str
    domain: str
    edge_id: str
    direction: str              # "long" | "short"
    quantity: float
    entry_price: float
    stop_price: float | None
    opened_on: str

    @property
    def notional(self) -> float:
        return abs(self.quantity * self.entry_price)

    @property
    def risk_amount(self) -> float | None:
        """Money at stake if the stop is hit.

        ``None`` when no stop was recorded — which is not zero risk, it is
        *unmeasured* risk, and the budget treats it as the full notional because
        a position with no exit plan can lose all of it.
        """
        if self.stop_price is None or self.entry_price <= 0:
            return None
        return abs(self.entry_price - self.stop_price) * abs(self.quantity)


@dataclass
class Account:
    """Equity, cash and open positions. Every field is stated, none is guessed."""

    equity: float | None = None
    cash: float | None = None
    positions: list[Position] = field(default_factory=list)
    as_of: str = field(default_factory=lambda: dt.datetime.now(dt.UTC).isoformat())

    @property
    def configured(self) -> bool:
        return self.equity is not None and self.equity > 0

    def require_equity(self) -> float:
        if not self.configured:
            raise AccountNotConfigured(
                "账户权益未配置。设置 POLYBOB_ACCOUNT_EQUITY 或在设置页录入实际权益;"
                "本项目不会替你猜一个本金,因为那会让'买多少'这个字段变成编造的数字。"
            )
        return float(self.equity)          # type: ignore[arg-type]

    # ------------------------------------------------------------- exposure
    def domain_notional(self, domain: str) -> float:
        return sum(p.notional for p in self.positions if p.domain == domain)

    def total_risk(self) -> float:
        """Sum of money at stake. A position with no stop counts as its full notional."""
        total = 0.0
        for p in self.positions:
            risk = p.risk_amount
            total += p.notional if risk is None else risk
        return total

    def correlated_risk(self, correlation: float = ASSUMED_CROSS_DOMAIN_CORRELATION) -> float:
        """Risk that does not diversify away, under an assumed correlation.

        Positions in the same domain are treated as fully correlated; across
        domains the assumed figure applies. This is deliberately pessimistic. The
        alternative — summing risk as if independent — is what makes two edges
        pointing the same way look like a hedge.
        """
        by_domain: dict[str, float] = {}
        for p in self.positions:
            risk = p.risk_amount
            by_domain[p.domain] = by_domain.get(p.domain, 0.0) + (p.notional if risk is None else risk)
        legs = list(by_domain.values())
        if not legs:
            return 0.0
        # sqrt(sum(x_i^2) + 2*rho*sum_{i<j} x_i x_j)
        squares = sum(x * x for x in legs)
        cross = sum(legs[i] * legs[j] for i in range(len(legs)) for j in range(i + 1, len(legs)))
        return math.sqrt(max(0.0, squares + 2.0 * correlation * cross))

    def snapshot(self) -> dict[str, Any]:
        equity = self.equity
        risk = self.total_risk()
        return {
            "configured": self.configured,
            "as_of": self.as_of,
            "equity": equity,
            "cash": self.cash,
            "open_positions": len(self.positions),
            "gross_notional": sum(p.notional for p in self.positions),
            "total_risk": risk,
            "correlated_risk": self.correlated_risk(),
            # Fractions are None rather than 0 when equity is unknown: 0% at risk
            # would read as a measurement of safety.
            "risk_fraction": None if not self.configured else risk / float(equity),  # type: ignore[arg-type]
            "positions_without_stop": sum(1 for p in self.positions if p.stop_price is None),
        }


__all__ = [
    "ASSUMED_CROSS_DOMAIN_CORRELATION",
    "MAX_DOMAIN_FRACTION",
    "MAX_POSITION_FRACTION",
    "MAX_TOTAL_RISK_FRACTION",
    "Account",
    "AccountNotConfigured",
    "Position",
]
