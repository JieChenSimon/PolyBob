"""Strategy promotion gate — the statistical checks a strategy must pass
before it may leave ``lab`` and drive real (or paper) capital.

Roughly 95% of backtested strategies fail live, and a search over enough
configurations will surface a Sharpe > 2 purely by chance. A rigorous process
therefore treats a backtest as a *filter that discards bad strategies*, not a
predictor of success. This module encodes the institutional checklist:

1. **Probabilistic / Deflated Sharpe Ratio** (Bailey & López de Prado) — is the
   Sharpe statistically distinguishable from what multiple-testing luck would
   produce, accounting for the number of trials, sample length, skew and
   kurtosis?
2. **Cost-stress** — does the edge survive realistic frictions, and (crucially)
   does Sharpe *degrade* as costs rise? A backtest whose Sharpe is insensitive
   to costs is a red flag for hidden bias.
3. **Out-of-sample stability** — do walk-forward test windows hold up rather
   than one lucky in-sample fit?
4. **Minimum track length** — is there enough data for the Sharpe to be
   trustworthy at all?

The gate returns an explicit PASS/FAIL with per-check reasons so no strategy is
promoted on a single impressive equity curve.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np
from scipy.stats import kurtosis, norm, skew

_EULER_MASCHERONI = 0.5772156649015329


def _sharpe_per_period(returns: np.ndarray) -> float:
    sd = returns.std(ddof=1)
    if sd == 0:
        return 0.0
    return float(returns.mean() / sd)


def annualized_sharpe(returns: Sequence[float], periods_per_year: int = 252) -> float:
    r = np.asarray(returns, dtype=float)
    if len(r) < 2:
        return 0.0
    return _sharpe_per_period(r) * math.sqrt(periods_per_year)


def probabilistic_sharpe_ratio(
    returns: Sequence[float], benchmark_sr_per_period: float = 0.0
) -> float:
    """P(true Sharpe > benchmark), correcting for sample size, skew and kurtosis.

    Returns a probability in [0, 1]. ``benchmark_sr_per_period`` is a
    *per-period* Sharpe (0 = "is the strategy better than nothing?").
    """
    r = np.asarray(returns, dtype=float)
    n = len(r)
    if n < 3 or r.std(ddof=1) == 0:
        return 0.0
    sr = _sharpe_per_period(r)
    sk = float(skew(r, bias=False))
    ku = float(kurtosis(r, fisher=False, bias=False))  # non-excess kurtosis
    denom = 1.0 - sk * sr + ((ku - 1.0) / 4.0) * sr * sr
    if denom <= 0:
        return 0.0
    z = (sr - benchmark_sr_per_period) * math.sqrt(n - 1) / math.sqrt(denom)
    return float(norm.cdf(z))


def expected_max_sharpe(n_trials: int, trial_sr_std: float) -> float:
    """Expected maximum per-period Sharpe from ``n_trials`` independent trials.

    This is the level a genuine edge must clear to not be explained by having
    tried many strategies (the SR0 term in the Deflated Sharpe Ratio).
    """
    if n_trials < 2 or trial_sr_std <= 0:
        return 0.0
    inv1 = norm.ppf(1.0 - 1.0 / n_trials)
    inv2 = norm.ppf(1.0 - 1.0 / (n_trials * math.e))
    return trial_sr_std * ((1.0 - _EULER_MASCHERONI) * inv1 + _EULER_MASCHERONI * inv2)


def deflated_sharpe_ratio(
    returns: Sequence[float],
    n_trials: int,
    trial_sr_std: float | None = None,
) -> float:
    """Deflated Sharpe Ratio = PSR evaluated against the expected-max Sharpe.

    Returns a probability in [0, 1]; values near 1 mean the observed Sharpe is
    unlikely to be a multiple-testing artefact. If the dispersion of Sharpe
    across trials is unknown, falls back to the null SR-estimator std
    ``1/sqrt(n-1)``.
    """
    r = np.asarray(returns, dtype=float)
    n = len(r)
    if n < 3:
        return 0.0
    if trial_sr_std is None:
        trial_sr_std = 1.0 / math.sqrt(n - 1)
    sr0 = expected_max_sharpe(n_trials, trial_sr_std)
    return probabilistic_sharpe_ratio(r, benchmark_sr_per_period=sr0)


def min_track_record_length(
    returns: Sequence[float],
    benchmark_sr_per_period: float = 0.0,
    confidence: float = 0.95,
) -> float:
    """Minimum number of observations for PSR(benchmark) to reach ``confidence``.

    If the current sample is shorter than this, the Sharpe is not yet
    trustworthy regardless of its value.
    """
    r = np.asarray(returns, dtype=float)
    if len(r) < 3 or r.std(ddof=1) == 0:
        return math.inf
    sr = _sharpe_per_period(r)
    if sr <= benchmark_sr_per_period:
        return math.inf
    sk = float(skew(r, bias=False))
    ku = float(kurtosis(r, fisher=False, bias=False))
    z = norm.ppf(confidence)
    var_term = 1.0 - sk * sr + ((ku - 1.0) / 4.0) * sr * sr
    return 1.0 + var_term * (z / (sr - benchmark_sr_per_period)) ** 2


@dataclass(frozen=True)
class CostStressResult:
    passed: bool
    base_sharpe: float
    stressed: list[tuple[float, float]]  # (cost_multiple, annualized_sharpe)
    degrades_with_cost: bool
    worst_sharpe: float
    reason: str


def cost_stress_test(
    returns_at_cost: Callable[[float], Sequence[float]],
    *,
    cost_multiples: Sequence[float] = (1.0, 2.0, 3.0),
    min_sharpe: float = 0.5,
    periods_per_year: int = 252,
) -> CostStressResult:
    """Re-run a strategy at rising cost levels and check the edge is real.

    ``returns_at_cost(multiple)`` must return the strategy's return series when
    per-trade costs are scaled by ``multiple``. Passes only if (a) Sharpe
    *falls* as costs rise — cost-insensitivity signals hidden bias — and (b)
    Sharpe at the highest cost level stays above ``min_sharpe``.
    """
    multiples = sorted(set(float(m) for m in cost_multiples))
    curve = [(m, annualized_sharpe(returns_at_cost(m), periods_per_year)) for m in multiples]
    base_sharpe = curve[0][1]
    worst_sharpe = curve[-1][1]
    # Monotone-ish degradation: the highest cost should not beat the lowest cost.
    degrades = worst_sharpe <= base_sharpe + 1e-9
    reasons = []
    if not degrades:
        reasons.append("Sharpe does not degrade as costs rise (possible hidden bias)")
    if worst_sharpe < min_sharpe:
        reasons.append(
            f"Sharpe under {multiples[-1]}x costs is {worst_sharpe:.2f} < {min_sharpe}"
        )
    passed = degrades and worst_sharpe >= min_sharpe
    return CostStressResult(
        passed=passed,
        base_sharpe=base_sharpe,
        stressed=curve,
        degrades_with_cost=degrades,
        worst_sharpe=worst_sharpe,
        reason="ok" if passed else "; ".join(reasons),
    )


@dataclass(frozen=True)
class PromotionCheck:
    name: str
    passed: bool
    value: float
    threshold: float
    detail: str


@dataclass(frozen=True)
class PromotionDecision:
    approved: bool
    checks: list[PromotionCheck] = field(default_factory=list)

    @property
    def failed_checks(self) -> list[PromotionCheck]:
        return [c for c in self.checks if not c.passed]

    def to_dict(self) -> dict:
        return {
            "approved": self.approved,
            "checks": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "value": c.value,
                    "threshold": c.threshold,
                    "detail": c.detail,
                }
                for c in self.checks
            ],
        }


@dataclass
class PromotionGate:
    """Combines the individual checks into a single PASS/FAIL decision."""

    n_trials: int = 1
    min_dsr: float = 0.95
    min_observations: int = 60
    min_oos_stability_rate: float = 0.5
    cost_min_sharpe: float = 0.5
    periods_per_year: int = 252

    def evaluate(
        self,
        returns: Sequence[float],
        *,
        cost_returns_fn: Callable[[float], Sequence[float]] | None = None,
        cost_multiples: Sequence[float] = (1.0, 2.0, 3.0),
        oos_stability_rate: float | None = None,
        trial_sr_std: float | None = None,
    ) -> PromotionDecision:
        r = np.asarray(returns, dtype=float)
        checks: list[PromotionCheck] = []

        # 1) Sample length.
        n = len(r)
        checks.append(
            PromotionCheck(
                name="min_observations",
                passed=n >= self.min_observations,
                value=float(n),
                threshold=float(self.min_observations),
                detail=f"{n} observations",
            )
        )

        # 2) Deflated Sharpe Ratio (multiple-testing corrected).
        dsr = deflated_sharpe_ratio(r, self.n_trials, trial_sr_std=trial_sr_std)
        checks.append(
            PromotionCheck(
                name="deflated_sharpe",
                passed=dsr >= self.min_dsr,
                value=round(dsr, 4),
                threshold=self.min_dsr,
                detail=f"DSR={dsr:.3f} over {self.n_trials} trial(s)",
            )
        )

        # 3) Cost-stress (only if a cost-parameterised return fn is provided).
        if cost_returns_fn is not None:
            stress = cost_stress_test(
                cost_returns_fn,
                cost_multiples=cost_multiples,
                min_sharpe=self.cost_min_sharpe,
                periods_per_year=self.periods_per_year,
            )
            checks.append(
                PromotionCheck(
                    name="cost_stress",
                    passed=stress.passed,
                    value=round(stress.worst_sharpe, 4),
                    threshold=self.cost_min_sharpe,
                    detail=stress.reason,
                )
            )

        # 4) Out-of-sample stability (walk-forward), if supplied.
        if oos_stability_rate is not None:
            checks.append(
                PromotionCheck(
                    name="oos_stability",
                    passed=oos_stability_rate >= self.min_oos_stability_rate,
                    value=round(oos_stability_rate, 4),
                    threshold=self.min_oos_stability_rate,
                    detail=f"{oos_stability_rate:.0%} of walk-forward windows stable",
                )
            )

        approved = all(c.passed for c in checks)
        return PromotionDecision(approved=approved, checks=checks)


__all__ = [
    "CostStressResult",
    "PromotionCheck",
    "PromotionDecision",
    "PromotionGate",
    "annualized_sharpe",
    "cost_stress_test",
    "deflated_sharpe_ratio",
    "expected_max_sharpe",
    "min_track_record_length",
    "probabilistic_sharpe_ratio",
]
