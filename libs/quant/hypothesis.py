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


def declared_trial_count(search_space: dict[str, Any] | None) -> int:
    """Count every declared filter/threshold/stratum combination."""
    if not search_space:
        return 1
    count = 1
    for dimension, options in search_space.items():
        if not str(dimension).strip():
            raise InadmissibleHypothesis("search_space dimensions must be named")
        values = tuple(options)
        if not values:
            raise InadmissibleHypothesis(f"search_space dimension '{dimension}' is empty")
        count *= len(values)
    return count


def validate_trial_configuration(search_space: dict[str, Any] | None, selected: dict[str, Any]) -> None:
    """Reject a reported winner outside the pre-registered search space."""
    declared = search_space or {}
    unknown = sorted(set(selected) - set(declared))
    missing = sorted(set(declared) - set(selected))
    if unknown or missing:
        raise InadmissibleHypothesis(
            f"selected configuration does not match pre-registration; missing={missing}, unknown={unknown}"
        )
    for dimension, value in selected.items():
        if value not in tuple(declared[dimension]):
            raise InadmissibleHypothesis(
                f"selected value {value!r} is outside pre-registered {dimension} grid"
            )


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
    # How many parameter configurations the backtest will search before it
    # reports a winner. A lookback grid of four, with the best one reported, is
    # four trials — not one — and the multiple-testing correction only stays
    # honest if the grid is declared here, before the search runs.
    n_configs: int = 1
    trial_family: str = ""
    # Fundamental filters, numeric thresholds, industry/asset strata, horizons,
    # directions and benchmarks all belong here when they can change the winner.
    search_space: dict[str, tuple[Any, ...]] = field(default_factory=dict)
    registered_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def __post_init__(self) -> None:
        if self.rationale is Rationale.NONE:
            raise InadmissibleHypothesis(
                f"'{self.hypothesis_id}' has no economic rationale. A pattern that "
                "only exists in a backtest is a fluke until theory says otherwise."
            )
        if self.n_configs < 1:
            raise InadmissibleHypothesis(
                f"'{self.hypothesis_id}': n_configs must be at least 1."
            )
        required = declared_trial_count(self.search_space)
        if self.n_configs < required:
            raise InadmissibleHypothesis(
                f"'{self.hypothesis_id}': n_configs={self.n_configs} understates "
                f"the declared search space ({required} combinations)."
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
    """Log of pre-registered hypotheses and their verdicts, keyed by id.

    One entry per ``hypothesis_id``. Re-running an experiment re-registers the
    same hypothesis rather than appending a second copy: duplicates would both
    inflate the trial count and split a hypothesis from its own result, which is
    exactly what happened when ``register`` blindly appended. Registration is
    therefore an upsert that preserves any result already recorded.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else REGISTRY_PATH
        self.entries: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text()).get("entries", [])
            except Exception:  # noqa: BLE001 - corrupt file starts fresh
                raw = []
            self.entries = _collapse_duplicates(raw)

    def register(self, hypothesis: Hypothesis) -> None:
        """Record a hypothesis *before* its backtest is run (idempotent by id)."""
        payload = hypothesis.to_dict()
        for entry in self.entries:
            if not entry.get("hypothesis"):
                continue          # an exploratory-sweep row, not a hypothesis
            if entry["hypothesis"]["hypothesis_id"] == hypothesis.hypothesis_id:
                # Keep the original registration timestamp: the whole point of
                # pre-registration is that it predates the result.
                payload["registered_at"] = entry["hypothesis"].get(
                    "registered_at", payload["registered_at"]
                )
                entry["hypothesis"] = payload
                self._save()
                return
        self.entries.append({"hypothesis": payload, "result": None})
        self._save()

    def record_result(self, hypothesis_id: str, result: dict[str, Any]) -> None:
        for entry in self.entries:
            spec = entry.get("hypothesis")
            if spec and spec["hypothesis_id"] == hypothesis_id:
                entry["result"] = result
                break
        self._save()

    def record_search(
        self, search_id: str, n_configs: int, description: str, *, outcome: str = "",
        trial_family: str = "", search_space: dict[str, Any] | None = None,
    ) -> None:
        """Record an exploratory sweep that produced no promoted hypothesis.

        The multiple-testing burden is set by how many things you *looked at*, not
        by how many you kept. This project ran a 184-configuration sweep of chart
        patterns and an 18-test directional sweep, found nothing, and registered
        neither — so the hurdle was computed as if only 35 trials had happened.
        Abandoned searches are the easiest kind to leave out and the most
        important to include: a search only lowers the bar if you forget it.

        These carry no ``result`` because there is nothing to claim. They exist
        purely to make :attr:`n_trials` honest.
        """
        required = declared_trial_count(search_space)
        if int(n_configs) < required:
            raise InadmissibleHypothesis(
                f"search '{search_id}' understates its search space: {n_configs} < {required}"
            )
        entry = {
            "search": {
                "search_id": search_id,
                "n_configs": int(n_configs),
                "description": description,
                "outcome": outcome or "no hypothesis promoted",
                "trial_family": trial_family,
                "search_space": search_space or {},
            },
            "result": None,
        }
        for i, existing in enumerate(self.entries):
            if existing.get("search", {}).get("search_id") == search_id:
                self.entries[i] = entry
                self._save()
                return
        self.entries.append(entry)
        self._save()

    @property
    def n_trials(self) -> int:
        """Every configuration ever tried — the honest multiple-testing count.

        Counts parameter configurations, not hypotheses: a hypothesis searched
        over a grid of four lookbacks consumed four trials, and correcting as if
        it were one understates the t-hurdle every other edge is judged against.

        Exploratory sweeps registered via :meth:`record_search` are included on
        the same footing. A configuration you tried and discarded still consumed a
        draw from the same distribution as the one you kept.
        """
        total = 0
        for entry in self.entries:
            spec = entry.get("hypothesis") or entry.get("search") or {}
            total += max(1, int(spec.get("n_configs", 1) or 1))
        return total

    @property
    def searches(self) -> list[dict[str, Any]]:
        """Exploratory sweeps that count as trials but claim no result."""
        return [e["search"] for e in self.entries if e.get("search")]

    @property
    def untested(self) -> list[str]:
        """Registered hypotheses with no result — pre-registered but never run.

        They still count as trials (they were part of the search), but a board
        must never claim them as evidence.
        """
        return [
            e["hypothesis"]["hypothesis_id"]
            for e in self.entries
            if e.get("hypothesis") and not e.get("result")
        ]

    def result_for(self, hypothesis_id: str) -> dict[str, Any] | None:
        for entry in self.entries:
            spec = entry.get("hypothesis")
            if spec and spec["hypothesis_id"] == hypothesis_id:
                return entry.get("result")
        return None

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"entries": self.entries}, indent=2, ensure_ascii=False)
        )


def _collapse_duplicates(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge repeat registrations of the same id, keeping the recorded result.

    Historic files were written by an append-only ``register``, so the same
    hypothesis can appear several times with the result attached to only one of
    them. Collapsing on load heals those files instead of leaving the trial
    count hostage to how many times a script was re-run.
    """
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for entry in entries:
        # Exploratory-sweep rows are keyed separately and have no result to merge.
        # Dropping them here — which an ``hypothesis_id``-only filter would do
        # silently — would delete trials from the count on the next load, quietly
        # lowering the hurdle every edge is judged against.
        search = entry.get("search") or {}
        if search.get("search_id"):
            key = f"search:{search['search_id']}"
            if key not in merged:
                merged[key] = {"search": search, "result": None}
                order.append(key)
            continue

        hypothesis = entry.get("hypothesis") or {}
        key = str(hypothesis.get("hypothesis_id", ""))
        if not key:
            continue
        if key not in merged:
            merged[key] = {"hypothesis": hypothesis, "result": entry.get("result")}
            order.append(key)
            continue
        if entry.get("result") and not merged[key].get("result"):
            merged[key]["result"] = entry["result"]
    return [merged[k] for k in order]


__all__ = [
    "declared_trial_count",
    "Hypothesis",
    "HypothesisRegistry",
    "InadmissibleHypothesis",
    "Rationale",
    "validate_trial_configuration",
]
