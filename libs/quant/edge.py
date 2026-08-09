"""One edge, one definition — used by the backtest and the live scan alike.

The insider edge currently exists three times:

1. ``scripts/insider_experiment.py`` — the study. It holds the *exit* rule
   (``forward_return``: enter at the first close on/after the filing, leave 20
   sessions later, excess of SPY, net of 10bps).
2. ``libs/quant/edge_instance.detect_insider_cluster`` — what the verdict and the
   live scan call. Entry only. **No exit.**
3. ``strategies/us_insider_cluster_buy/strategy.py`` — a third ``find_clusters``.

They share ``cluster_buys``, so the detection rule agrees. Nothing else does. The
consequence is precise and bad: the board approves a *strategy with a 20-session
hold measured against SPY net of costs*, and the product surfaces a *signal with
no exit at all*. Those are different objects, and only the first one has evidence.

This is the gap NautilusTrader closes with a "common core": one kernel shared by
backtest, sandbox and live, with only the adapters differing, so the business
logic cannot drift between contexts. The unit of work here is not an order router
but an *edge*, so the common core is this protocol. An :class:`Edge` declares
everything that decides a result — universe, entry, exit, cost, hold, direction —
and both consumers read the same object:

- :mod:`libs.quant.edge_backtest` replays it over history to produce evidence.
- the live scan asks it what is firing today, and reports the exit *it* declares.

If the numbers on the board and the instructions on the page ever disagree again,
it will be because someone wrote a second definition — and there is now an obvious
place for the first one, so that is a visible act rather than an accident.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, Sequence, runtime_checkable


class Direction(str, Enum):
    """What acting on the edge means. ``AVOID`` is not a position."""

    LONG = "long"
    SHORT = "short"
    AVOID = "avoid"


@dataclass(frozen=True)
class Signal:
    """The edge fired on one instrument on one date.

    ``as_of`` is when the information became *public*, not when the underlying
    transaction happened. For the insider edge that is the filing date; using the
    trade date would be look-ahead worth several percent.
    """

    symbol: str
    fired_on: str                 # ISO date — the public-information date
    direction: Direction
    evidence_zh: str
    evidence_en: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def is_position(self) -> bool:
        return self.direction in (Direction.LONG, Direction.SHORT)


@dataclass(frozen=True)
class ExitRule:
    """How the position is closed — the half that was missing from the live side.

    A signal without this is not actionable and, more importantly, is not the
    thing the study measured. Stating it on the edge means the page can tell you
    when to get out using the same rule the t-statistic was computed under.
    """

    hold_sessions: int
    benchmark: str | None         # excess return is measured against this
    cost_bps: float

    def describe_zh(self) -> str:
        bench = f",超额相对 {self.benchmark}" if self.benchmark else ""
        return f"持有 {self.hold_sessions} 个交易日后平仓{bench},单边成本 {self.cost_bps:.0f}bps"


@runtime_checkable
class Edge(Protocol):
    """The single definition of one edge.

    Implementations live next to their detection logic. The protocol is what the
    backtest and the scanner both program against, so neither can quietly acquire
    its own idea of what the rule is.
    """

    id: str
    domain: str
    hypothesis_id: str
    direction: Direction
    exit_rule: ExitRule

    def universe(self, as_of: dt.datetime) -> Sequence[str]:
        """Instruments this edge is allowed to fire on, as known at ``as_of``.

        Part of the hypothesis, not a convenience: "insider clusters predict
        returns" is a different claim over mega-caps than over all SEC filers, and
        a universe that differs between the study and the scan makes the evidence
        describe a different population from the one being traded.
        """
        ...

    def detect(self, symbol: str, as_of: dt.datetime) -> Signal | None:
        """Whether the edge fires on ``symbol`` using only what was known at ``as_of``.

        Reads must go through :func:`libs.data.store.read` with this ``as_of``, so
        look-ahead is structurally unavailable rather than merely discouraged.
        """
        ...


@dataclass(frozen=True)
class EdgeSpecification:
    """The declarative half of an edge, shared by every implementation.

    Kept separate from the detection code so that a spec can be inspected,
    printed and compared without importing a provider client — the board needs
    the numbers, not the network.
    """

    id: str
    domain: str
    hypothesis_id: str
    direction: Direction
    exit_rule: ExitRule
    universe_description: str
    max_evidence_age_days: int
    notes: str = ""

    def summary_zh(self) -> str:
        action = {"long": "做多", "short": "做空", "avoid": "回避"}[self.direction.value]
        return f"{action} · {self.exit_rule.describe_zh()} · 范围:{self.universe_description}"


__all__ = ["Direction", "Edge", "EdgeSpecification", "ExitRule", "Signal"]
