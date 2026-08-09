"""Inference that does not assume every event is an independent observation.

Both event studies on the promotion board reported a plain i.i.d. t-statistic:
``t = mean / (sd / sqrt(n))``. That formula is only valid when the n returns are
independent draws, and in an event study they are not:

- **Overlapping holding windows.** The insider edge holds for 20 sessions. Two
  clusters that file three days apart share 17 sessions of the same price path,
  so their excess returns are close to the same observation counted twice.
- **Cross-sectional correlation.** Events bunch in calendar time — insiders buy
  after a selloff, retail crowds during the same rally — and instruments in the
  same market move together. The altcoin edge is the extreme case: eight majors
  that co-move, crowding simultaneously. Its 241 events fall in 13 distinct
  weeks.
- **Severe skew.** The insider edge's mean excess is +5.08% against a median of
  +0.55%. A handful of right-tail events carry the mean, and a t-test on skewed,
  dependent data over-reads that as significance.

Measured on the same real data, correcting only for dependence:

    us_insider_cluster_buy   iid t = 5.40  ->  weekly-clustered t = 2.31
    altcoin_retail_crowding  iid t = 6.38  ->  weekly-clustered t = 1.74

against a multiple-testing hurdle of 3.77. Both edges fail. The project spent
real effort on the hurdle — deflated for 35 trials — while the statistic being
compared against it was inflated by using ``sqrt(753)`` where the effective
count was closer to ``sqrt(40)``. Correcting one and not the other raises the
bar and then walks around it.

So this module is the inference layer the event studies should have used:
clustered standard errors, a bootstrap interval that does not assume symmetry,
and a sign test that does not care about the tail at all. An edge that only
survives under i.i.d. assumptions is not an edge; it is an artefact of the
formula.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

import numpy as np

ClusterBy = Literal["day", "week", "month"]


def cluster_key(date: str, by: ClusterBy) -> str:
    """Which independence unit a date belongs to.

    The unit must be at least as long as the holding period; otherwise two
    "independent" clusters still share most of their return window. Weekly is
    the right default for a five-session hold, monthly for twenty.
    """
    day = dt.date.fromisoformat(date[:10])
    if by == "day":
        return day.isoformat()
    if by == "week":
        year, week, _ = day.isocalendar()
        return f"{year}-W{week:02d}"
    return day.strftime("%Y-%m")


def recommended_cluster(hold_days: int) -> ClusterBy:
    """The smallest unit that does not leave windows overlapping across clusters."""
    if hold_days <= 3:
        return "day"
    if hold_days <= 10:
        return "week"
    return "month"


@dataclass(frozen=True)
class ClusteredResult:
    """One edge's evidence, stated without assuming independence."""

    n: int                         # raw events
    n_clusters: int                # effective independent units
    mean: float
    median: float
    win_rate: float
    t_iid: float                   # what the old code reported
    t_clustered: float             # what it should have reported
    t_hurdle: float
    significant: bool
    bootstrap_lo: float | None     # 95% CI on the mean, cluster-resampled
    bootstrap_hi: float | None
    sign_test_p: float | None      # does the *median* beat zero?
    skew_ratio: float | None       # mean / median — how tail-driven the mean is
    cluster_by: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "n_clusters": self.n_clusters,
            "mean_excess_pct": round(self.mean * 100, 3),
            "median_excess_pct": round(self.median * 100, 3),
            "win_rate": round(self.win_rate, 4),
            "t_stat": round(self.t_clustered, 2),
            "t_stat_iid": round(self.t_iid, 2),
            "t_hurdle": round(self.t_hurdle, 2),
            "significant": self.significant,
            "bootstrap_ci_pct": (
                None if self.bootstrap_lo is None
                else [round(self.bootstrap_lo * 100, 3), round(self.bootstrap_hi * 100, 3)]
            ),
            "sign_test_p": None if self.sign_test_p is None else round(self.sign_test_p, 4),
            "skew_ratio": None if self.skew_ratio is None else round(self.skew_ratio, 2),
            "cluster_by": self.cluster_by,
            "inference": "cluster_robust",
            "warnings": list(self.warnings),
        }


def _cluster_means(
    returns: Sequence[float], dates: Sequence[str], by: ClusterBy
) -> tuple[np.ndarray, list[str]]:
    buckets: dict[str, list[float]] = {}
    for value, date in zip(returns, dates):
        if not np.isfinite(value):
            continue
        buckets.setdefault(cluster_key(date, by), []).append(float(value))
    keys = sorted(buckets)
    return np.array([float(np.mean(buckets[k])) for k in keys]), keys


def _sign_test_p(returns: np.ndarray) -> float | None:
    """Two-sided binomial test that the median return is zero.

    Immune to the tail entirely: it asks only how often the trade won. An edge
    whose mean is nine times its median needs this check, because the mean is a
    statement about a few events and the median is a statement about the typical
    one.
    """
    from scipy.stats import binomtest

    wins = int((returns > 0).sum())
    trials = int((returns != 0).sum())
    if trials < 10:
        return None
    return float(binomtest(wins, trials, 0.5, alternative="two-sided").pvalue)


def analyse(
    returns: Sequence[float],
    dates: Sequence[str],
    *,
    t_hurdle: float,
    hold_days: int,
    cluster_by: ClusterBy | None = None,
    bootstrap_draws: int = 5000,
    seed: int = 20260807,
    min_clusters: int = 20,
) -> ClusteredResult:
    """Judge an event study's returns without assuming the events are independent.

    ``returns`` and ``dates`` are per-event and parallel. The t-statistic is
    computed on **cluster means**, which is the standard fix when observations
    within a group share a shock: it trades raw count for validity, and the raw
    count was never real to begin with.

    The bootstrap resamples *whole clusters*, so the interval inherits the same
    dependence structure instead of pretending each event can be redrawn alone.
    """
    raw = np.asarray([r for r in returns if np.isfinite(r)], dtype=float)
    by = cluster_by or recommended_cluster(hold_days)
    means, keys = _cluster_means(returns, dates, by)

    warnings: list[str] = []
    n, g = len(raw), len(means)
    if n == 0 or g == 0:
        return ClusteredResult(0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, t_hurdle, False,
                               None, None, None, None, by, ["no usable returns"])

    sd_iid = raw.std(ddof=1) if n > 1 else 0.0
    t_iid = float(raw.mean() / (sd_iid / np.sqrt(n))) if sd_iid > 0 else 0.0

    if g < 2:
        warnings.append("only one independence cluster — no inference is possible")
        t_clustered = 0.0
    else:
        sd_g = means.std(ddof=1)
        t_clustered = float(means.mean() / (sd_g / np.sqrt(g))) if sd_g > 0 else 0.0

    if g < min_clusters:
        # Cluster-robust standard errors are themselves unreliable with few
        # clusters; the fix for that is more calendar coverage, not a bigger n.
        warnings.append(
            f"only {g} independence clusters (<{min_clusters}); the clustered "
            "t-statistic is itself imprecise — extend the sample period, not the "
            "event count"
        )

    median = float(np.median(raw))
    mean = float(raw.mean())
    skew_ratio = (mean / median) if median != 0 else None
    if skew_ratio is not None and abs(skew_ratio) > 3:
        warnings.append(
            f"mean is {skew_ratio:.1f}x the median — the average is carried by a "
            "few tail events, so the typical trade looks nothing like it"
        )

    lo = hi = None
    if g >= 2:
        rng = np.random.default_rng(seed)
        draws = rng.integers(0, g, size=(bootstrap_draws, g))
        samples = means[draws].mean(axis=1)
        lo, hi = (float(np.percentile(samples, 2.5)), float(np.percentile(samples, 97.5)))
        if lo <= 0 <= hi:
            warnings.append("the 95% bootstrap interval on the mean contains zero")

    return ClusteredResult(
        n=n, n_clusters=g, mean=mean, median=median,
        win_rate=float((raw > 0).mean()),
        t_iid=t_iid, t_clustered=t_clustered, t_hurdle=t_hurdle,
        significant=bool(abs(t_clustered) >= t_hurdle and g >= min_clusters),
        bootstrap_lo=lo, bootstrap_hi=hi,
        sign_test_p=_sign_test_p(raw), skew_ratio=skew_ratio,
        cluster_by=by, warnings=warnings,
    )


__all__ = ["ClusterBy", "ClusteredResult", "analyse", "cluster_key", "recommended_cluster"]
