"""Pre-registration of strategy hypotheses — theory before compute.

The wide sweep (200+ configurations, 0 promoted) failed the way the literature
predicts: it let computational power, not investment theory, decide what to
test. Worse, ``range_contraction`` was created by *looking at* a losing result
and flipping its sign — textbook data snooping.

The methodological fix, from Bailey & López de Prado and the replication
literature:

- **Theory first.** "Investment theory, not computational power, should motivate
  what experiments are worth conducting." An hypothesis without an ex-ante
  economic rationale is not admissible, however good its backtest looks.
- **Pre-register.** Direction, universe, horizon, costs and success criteria are
  fixed *before* the backtest runs, so the result cannot be reverse-engineered.
- **Count every trial.** The registry knows how many hypotheses were tested,
  which feeds the deflated Sharpe / PBO correction honestly.

Anomalies that replicate out-of-sample share an economic story (risk premium or
behavioural bias + limits to arbitrage): momentum, value, profitability,
investment. Pure chart patterns with no such story — the liquidity/distress
corner of the "factor zoo", where ~95 of 102 trading-friction variables fail —
do not. :class:`Hypothesis` enforces that distinction structurally.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

REGISTRY_PATH = Path("data/hypothesis_registry.json")


class Rationale(str, Enum):
    """Why the edge should exist. ``NONE`` is inadmissible by design."""

    RISK_PREMIUM = "risk_premium"          # compensation for bearing risk
    BEHAVIOURAL = "behavioural"            # investor bias + limits to arbitrage
    STRUCTURAL = "structural"              # flows/constraints/market design
    NONE = "none"                          # no theory -> rejected


class InadmissibleHypothesis(ValueError):
    """Raised when a hypothesis has no economic rationale (a chart pattern)."""


@dataclass(frozen=True)
class Hypothesis:
    """A pre-registered, falsifiable claim about why an edge exists."""

    hypothesis_id: str
    claim: str                    # one or two sentences — if you need a page, it's overfit
    rationale: Rationale
    mechanism: str                # *why* the mispricing survives arbitrage
    literature: str               # prior evidence (replication / cross-market)
    direction: str                # "long_winners" etc. — fixed BEFORE testing
    universe: str
    horizon_days: int
    cost_bps: float
    min_sharpe: float = 0.5
    registered_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def __post_init__(self) -> None:
        if self.rationale is Rationale.NONE:
            raise InadmissibleHypothesis(
                f"'{self.hypothesis_id}' has no economic rationale. A pattern that "
                "only exists in a backtest is a fluke until theory says otherwise."
            )
        if not self.mechanism.strip():
            raise InadmissibleHypothesis(
                f"'{self.hypothesis_id}' must state why the edge is not arbitraged away."
            )
        if len(self.claim.split(".")) > 4:
            raise InadmissibleHypothesis(
                f"'{self.hypothesis_id}': the claim must fit in one or two sentences."
            )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["rationale"] = self.rationale.value
        return payload


class HypothesisRegistry:
    """Append-only log of pre-registered hypotheses and their verdicts."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else REGISTRY_PATH
        self.entries: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self.entries = json.loads(self.path.read_text()).get("entries", [])
            except Exception:  # noqa: BLE001 - corrupt file starts fresh
                self.entries = []

    def register(self, hypothesis: Hypothesis) -> None:
        """Record a hypothesis *before* its backtest is run."""
        self.entries.append({"hypothesis": hypothesis.to_dict(), "result": None})
        self._save()

    def record_result(self, hypothesis_id: str, result: dict[str, Any]) -> None:
        for entry in self.entries:
            if entry["hypothesis"]["hypothesis_id"] == hypothesis_id:
                entry["result"] = result
                break
        self._save()

    @property
    def n_trials(self) -> int:
        """Every hypothesis ever registered — the honest multiple-testing count."""
        return len(self.entries)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"entries": self.entries}, indent=2, ensure_ascii=False)
        )


__all__ = [
    "Hypothesis",
    "HypothesisRegistry",
    "InadmissibleHypothesis",
    "Rationale",
]
