"""Concept-drift circuit breaker (P8c).

Financial models decay when the live distribution drifts away from the one they
were validated on. Rather than discover this through mounting losses, this
monitor watches a *recent* window of a feature or return series against a fixed
*reference* window and, when the shift is significant, flips a circuit breaker
that the rest of the system can read (e.g. an API endpoint, or a flag the
auto-trader could consult) to halt or de-risk.

Design follows model-monitoring best practice:

- **Fixed reference bins.** The reference window is set once (from a stable
  baseline) and held; comparisons reuse it, so a slowly moving current window
  cannot mask drift by dragging the baseline with it.
- **PSI + KS, per series.** Drift is univariate, so each named series is scored
  independently via :func:`libs.quant.drift.detect_drift` (PSI screening plus a
  Kolmogorov–Smirnov corroboration).
- **Tiered response.** PSI ``< 0.10`` is stable, ``0.10–0.25`` a *watch*, and
  ``>= 0.25`` (``DriftLevel.SIGNIFICANT``) trips the breaker. Halting on the
  significant tier — not the first moderate wobble — avoids flapping.
- **Latched breaker with explicit re-enable.** Once tripped the breaker stays
  tripped until :meth:`reset` is called, mirroring the human-in-the-loop
  re-validation/retrain workflow a real kill-switch demands.

Sources applied:
- Model drift / PSI thresholds and "fix bins from baseline; combine PSI with a
  second test; halt at ~0.25": Statsig, Coralogix, Fiddler AI, Towards Data
  Science (see task report).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Iterable

from libs.quant.drift import DriftLevel, DriftReport, detect_drift


@dataclass
class _Series:
    reference: list[float] = field(default_factory=list)
    current: deque[float] = field(default_factory=deque)


class DriftMonitor:
    """Latching drift circuit breaker over one or more named numeric series."""

    def __init__(
        self,
        *,
        window: int = 200,
        min_samples: int = 30,
        halt_level: DriftLevel = DriftLevel.SIGNIFICANT,
        bins: int = 10,
        ks_alpha: float = 0.05,
    ) -> None:
        if window < 2:
            raise ValueError("window must be >= 2")
        self.window = window
        self.min_samples = max(2, int(min_samples))
        self.halt_level = halt_level
        self.bins = bins
        self.ks_alpha = ks_alpha
        self._series: dict[str, _Series] = {}
        self._halted = False
        self._halt_reasons: list[str] = []
        self._tripped_at: datetime | None = None

    # ----------------------------------------------------------- ingestion

    def _get(self, name: str) -> _Series:
        series = self._series.get(name)
        if series is None:
            series = _Series(reference=[], current=deque(maxlen=self.window))
            self._series[name] = series
        return series

    def set_reference(self, name: str, values: Iterable[float]) -> None:
        """Fix the baseline window for ``name`` (bins are held from here)."""
        series = self._get(name)
        series.reference = [float(v) for v in values]

    def observe(self, name: str, value: float) -> None:
        """Append one live observation to the rolling current window."""
        self._get(name).current.append(float(value))

    def extend(self, name: str, values: Iterable[float]) -> None:
        for value in values:
            self.observe(name, value)

    # ------------------------------------------------------------ analysis

    def evaluate(self, name: str) -> DriftReport | None:
        """Drift verdict for one series, or ``None`` if under-sampled."""
        series = self._series.get(name)
        if series is None:
            return None
        if len(series.reference) < self.min_samples or len(series.current) < self.min_samples:
            return None
        return detect_drift(
            series.reference,
            list(series.current),
            bins=self.bins,
            ks_alpha=self.ks_alpha,
        )

    def evaluate_all(self) -> dict[str, DriftReport]:
        reports: dict[str, DriftReport] = {}
        for name in self._series:
            report = self.evaluate(name)
            if report is not None:
                reports[name] = report
        return reports

    def _level_trips(self, level: DriftLevel) -> bool:
        order = {DriftLevel.NONE: 0, DriftLevel.MODERATE: 1, DriftLevel.SIGNIFICANT: 2}
        return order[level] >= order[self.halt_level]

    def check(self) -> bool:
        """Evaluate every series and latch the breaker if any trips. Returns
        the (possibly newly latched) halt state."""
        reasons: list[str] = []
        for name, report in self.evaluate_all().items():
            if self._level_trips(report.level):
                reasons.append(f"{name}: {report.detail}")
        if reasons and not self._halted:
            self._halted = True
            self._halt_reasons = reasons
            self._tripped_at = datetime.now(UTC)
        elif reasons:
            self._halt_reasons = reasons
        return self._halted

    def should_halt(self) -> bool:
        """True once the breaker has latched. Re-checks current windows first so
        an on-demand caller sees fresh state without a separate ``check()``."""
        self.check()
        return self._halted

    def reset(self) -> None:
        """Clear the latch (explicit human-in-the-loop re-enable)."""
        self._halted = False
        self._halt_reasons = []
        self._tripped_at = None

    # -------------------------------------------------------------- status

    def status(self) -> dict:
        reports = {name: report.to_dict() for name, report in self.evaluate_all().items()}
        return {
            "halted": self._halted,
            "halt_level": self.halt_level.value,
            "reasons": list(self._halt_reasons),
            "tripped_at": self._tripped_at.isoformat() if self._tripped_at else None,
            "series": {
                name: {
                    "reference_size": len(s.reference),
                    "current_size": len(s.current),
                }
                for name, s in self._series.items()
            },
            "reports": reports,
        }


__all__ = ["DriftMonitor"]
