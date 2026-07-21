"""Concept-drift detection for features and live strategy performance.

Financial markets exhibit concept drift: the statistical properties of the data
change over time, so a model fit on one regime silently decays in the next.
Rather than discover this through mounting losses, a professional stack watches
for distribution shift and flags it — the trigger for re-validation or
re-training, and an input to model circuit breakers.

Two complementary detectors:

- **PSI (Population Stability Index)** — the standard industry measure of how
  much a distribution has moved versus a baseline. Conventional reading:
  ``< 0.10`` stable, ``0.10–0.25`` moderate shift, ``> 0.25`` significant shift.
- **Two-sample Kolmogorov–Smirnov test** — a distribution-free hypothesis test
  for "are these two samples from the same distribution?", giving a p-value.

:func:`detect_drift` combines them into one :class:`DriftReport`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
from scipy.stats import ks_2samp


class DriftLevel(str, Enum):
    NONE = "none"
    MODERATE = "moderate"
    SIGNIFICANT = "significant"


def population_stability_index(
    expected: np.ndarray | list[float],
    actual: np.ndarray | list[float],
    *,
    bins: int = 10,
    epsilon: float = 1e-6,
) -> float:
    """PSI between a baseline (``expected``) and a new sample (``actual``).

    Bin edges are quantiles of the baseline so each baseline bin holds a
    comparable mass; ``epsilon`` guards empty bins against divide-by-zero.
    """
    expected_arr = np.asarray(expected, dtype=float)
    actual_arr = np.asarray(actual, dtype=float)
    if expected_arr.size == 0 or actual_arr.size == 0:
        return 0.0

    quantiles = np.linspace(0, 1, bins + 1)
    edges = np.unique(np.quantile(expected_arr, quantiles))
    if edges.size < 2:
        # Degenerate baseline (all equal) — fall back to a single spread bin.
        edges = np.array([expected_arr.min() - 1e-9, expected_arr.max() + 1e-9])
    edges[0], edges[-1] = -np.inf, np.inf

    expected_pct = np.histogram(expected_arr, bins=edges)[0] / expected_arr.size
    actual_pct = np.histogram(actual_arr, bins=edges)[0] / actual_arr.size

    expected_pct = np.clip(expected_pct, epsilon, None)
    actual_pct = np.clip(actual_pct, epsilon, None)

    return float(np.sum((actual_pct - expected_pct) * np.log(actual_pct / expected_pct)))


def psi_level(psi: float) -> DriftLevel:
    if psi < 0.10:
        return DriftLevel.NONE
    if psi < 0.25:
        return DriftLevel.MODERATE
    return DriftLevel.SIGNIFICANT


@dataclass(frozen=True)
class DriftReport:
    level: DriftLevel
    psi: float
    ks_statistic: float
    ks_pvalue: float
    drifted: bool
    detail: str

    def to_dict(self) -> dict:
        return {
            "level": self.level.value,
            "psi": round(self.psi, 4),
            "ks_statistic": round(self.ks_statistic, 4),
            "ks_pvalue": round(self.ks_pvalue, 4),
            "drifted": self.drifted,
            "detail": self.detail,
        }


def detect_drift(
    reference: np.ndarray | list[float],
    current: np.ndarray | list[float],
    *,
    bins: int = 10,
    ks_alpha: float = 0.05,
) -> DriftReport:
    """Combine PSI and a KS test into a single drift verdict.

    ``drifted`` is True when PSI signals at least a moderate shift *or* the KS
    test rejects distributional equality at ``ks_alpha``.
    """
    ref = np.asarray(reference, dtype=float)
    cur = np.asarray(current, dtype=float)
    psi = population_stability_index(ref, cur, bins=bins)
    level = psi_level(psi)

    if ref.size >= 2 and cur.size >= 2:
        ks_stat, ks_p = ks_2samp(ref, cur)
        ks_stat, ks_p = float(ks_stat), float(ks_p)
    else:
        ks_stat, ks_p = 0.0, 1.0

    ks_rejects = ks_p < ks_alpha
    drifted = level is not DriftLevel.NONE or ks_rejects
    detail = f"PSI={psi:.3f} ({level.value}); KS p={ks_p:.3f}"
    if drifted:
        detail += " -> drift detected; re-validate/re-train"
    return DriftReport(
        level=level,
        psi=psi,
        ks_statistic=ks_stat,
        ks_pvalue=ks_p,
        drifted=drifted,
        detail=detail,
    )


__all__ = [
    "DriftLevel",
    "DriftReport",
    "detect_drift",
    "population_stability_index",
    "psi_level",
]
