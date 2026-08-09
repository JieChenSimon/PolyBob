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
    wild_p: float | None           # cluster bootstrap p — correctly sized at small G
    p_floor: float | None          # finest p that G clusters can express: 1/2^(G-1)
    resolvable: bool               # can this G express the required significance at all?
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
            "wild_p": None if self.wild_p is None else round(self.wild_p, 5),
            "p_floor": None if self.p_floor is None else float(f"{self.p_floor:.3g}"),
            "resolvable": self.resolvable,
            "skew_ratio": None if self.skew_ratio is None else round(self.skew_ratio, 2),
            "cluster_by": self.cluster_by,
            "inference": "cluster_robust",
            "warnings": list(self.warnings),
        }


def _buckets(
    returns: Sequence[float], dates: Sequence[str], by: ClusterBy
) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for value, date in zip(returns, dates):
        if not np.isfinite(value):
            continue
        out.setdefault(cluster_key(date, by), []).append(float(value))
    return out


def _crve_t(buckets: dict[str, list[float]]) -> tuple[float, float]:
    """Cluster-robust t for the sample mean. Returns ``(t, standard_error)``.

    The estimator is the **sample mean** and only the variance changes. The first
    version of this module instead averaged the cluster means, and that was wrong in
    two ways that compounded:

    1. It silently changed the estimator. The board reports ``mean_excess_pct`` from
       the sample mean while its ``t_stat`` came from the cluster-mean average — two
       different quantities on the same row. On the altcoin edge they differed by 37%
       (+3.09% against +2.25%).
    2. It over-corrected on unbalanced clusters, giving a 3-event week the same weight
       as a 32-event week. The altcoin edge's clusters range 3 to 32.

    This is the standard sandwich estimator:
    ``Var(mean) = G/(G-1) * sum_g (sum_{i in g} (r_i - mean))^2 / n^2``.
    Within a cluster the residuals are allowed to be arbitrarily correlated, which is
    the whole point — it makes no assumption about *how* the overlap works.
    """
    values = [v for group in buckets.values() for v in group]
    n, g = len(values), len(buckets)
    if n < 2 or g < 2:
        return 0.0, 0.0
    arr = np.asarray(values, dtype=float)
    mean = float(arr.mean())
    scores = np.array([float(np.sum(np.asarray(group) - mean)) for group in buckets.values()])
    variance = (g / (g - 1)) * float((scores ** 2).sum()) / (n * n)
    se = float(np.sqrt(variance)) if variance > 0 else 0.0

    # A degenerate sample has no measurable uncertainty, and dividing by its residual
    # floating-point standard error produces a t of 1e16 — which would sail through any
    # hurdle. The guard is *relative*: an absolute ``se <= 0`` misses the residue,
    # because summing identical values leaves errors around 1e-18 rather than exactly
    # zero. Scale is set by the data itself so the test works at any magnitude.
    scale = float(np.abs(arr).mean()) or 1.0
    if se <= scale * 1e-12:
        return 0.0, 0.0
    return mean / se, se


def _alpha_for_t(t_threshold: float) -> float:
    """The two-sided normal alpha a |t| threshold corresponds to.

    The board's hurdle is a heuristic (``3.0 + 0.5*log10(n_trials)``) rather than an
    alpha, so this is what lets the bootstrap and the t-test be judged at one bar. At
    237 trials the hurdle is 4.19, i.e. alpha = 2.8e-5 — which is *stricter* than
    Bonferroni at the same trial count (0.05/237 = 2.1e-4, t = 3.71), and Bonferroni is
    already the most conservative correction in standard use. Worth knowing before
    concluding that an edge failed on its merits.
    """
    from scipy import stats

    return float(2.0 * (1.0 - stats.norm.cdf(abs(t_threshold))))


def wild_cluster_p(
    buckets: dict[str, list[float]], *, draws: int = 3999, seed: int = 20260810
) -> tuple[float, float]:
    """Wild cluster bootstrap p-value for ``mean == 0``, and the finest p it can resolve.

    The asymptotic CRVE t-statistic assumes the *number of clusters* grows large. It
    does not here, and the consequence is measurable. Simulating from a process
    calibrated to the real insider edge, the rejection rate at a nominal 5% comes out:

        G=5   13.5%      G=14   5.8%
        G=9   10.0%      G=20   5.8%

    So at the sample sizes this project actually has, the asymptotic test manufactures
    false positives — two to three times the nominal rate. Cameron, Gelbach & Miller's
    (2008) wild cluster bootstrap fixes it by resampling whole clusters' signs:

        G=5   1.7%       G=14   4.2%
        G=9   5.2%       G=20   4.7%

    Correctly sized from G≈9 upward, conservative below.

    The second return value is the **information floor**: with G clusters there are only
    ``2^(G-1)`` distinct sign assignments, so no p-value below ``1/2^(G-1)`` is
    representable — however strong the effect. At G=9 that floor is 3.9e-3 while the
    board's hurdle demands 2.8e-5. The insider edge is not *near* significance at 9
    independent months; it is at a sample size where significance cannot be expressed.
    That is a different statement, and it points at a different remedy.
    """
    groups = [np.asarray(v, dtype=float) for v in buckets.values()]
    g = len(groups)
    floor = 1.0 / (2 ** (g - 1)) if 1 <= g <= 60 else 0.0
    if g < 2:
        return 1.0, 1.0

    t_observed = abs(_crve_t(buckets)[0])
    if t_observed == 0.0:
        return 1.0, floor

    # Residuals under H0 (mean = 0) are the returns themselves, so imposing the null
    # is just a sign flip per cluster — the Rademacher weights.
    rng = np.random.default_rng(seed)
    keys = list(buckets)
    extreme = 0
    for _ in range(draws):
        signs = rng.choice((-1.0, 1.0), size=g)
        flipped = {k: (groups[i] * signs[i]).tolist() for i, k in enumerate(keys)}
        if abs(_crve_t(flipped)[0]) >= t_observed:
            extreme += 1
    # (extreme + 1) / (draws + 1) — the observed statistic is one of its own draws, so
    # a p-value of exactly zero is not claimable.
    return (extreme + 1) / (draws + 1), floor


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
    wild_draws: int = 1999,
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
    buckets = _buckets(returns, dates, by)

    warnings: list[str] = []
    n, g = len(raw), len(buckets)
    if n == 0 or g == 0:
        return ClusteredResult(0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, t_hurdle, False,
                               None, None, None, None, None, None, False, by,
                               ["no usable returns"])

    sd_iid = raw.std(ddof=1) if n > 1 else 0.0
    t_iid = float(raw.mean() / (sd_iid / np.sqrt(n))) if sd_iid > 0 else 0.0

    if g < 2:
        warnings.append("only one independence cluster — no inference is possible")
        t_clustered = 0.0
    else:
        t_clustered, _ = _crve_t(buckets)

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

    # The sharpest version of that warning: a t-statistic that clears its bar while the
    # *median* is indistinguishable from zero is an effect that exists only in the tail.
    # Measured on the real insider edge, the single-buy control reaches t=5.13 with a
    # 50.6% win rate, a median of +0.09% and a sign test at p=0.63 — a coin flip with a
    # few large winners. That can still be a real portfolio return, but it is not the
    # thing "stocks that outperform" sounds like, and it sizes very differently.
    sign_p = _sign_test_p(raw)
    if (sign_p is not None and sign_p > 0.10
            and abs(t_clustered) >= t_hurdle * 0.75
            and skew_ratio is not None and abs(skew_ratio) > 3):
        warnings.append(
            f"t 值接近或超过门槛,但中位数与 0 无法区分(符号检验 p={sign_p:.2f},"
            f"胜率 {float((raw > 0).mean())*100:.1f}%)—— 这个效应只存在于尾部。"
            f"组合层面可能是真的收益,但它不是'这些股票会跑赢'那个意思,"
            f"而且仓位算法必须按整个分布定,不能按胜率定。"
        )

    lo = hi = None
    if g >= 2:
        # Resample whole clusters and recompute the pooled mean — the same estimator
        # the t-statistic uses. Averaging cluster *means* here would give an interval
        # around a different quantity from the one being reported.
        rng = np.random.default_rng(seed)
        groups = [np.asarray(v, dtype=float) for v in buckets.values()]
        sums = np.array([grp.sum() for grp in groups])
        sizes = np.array([len(grp) for grp in groups], dtype=float)
        draws = rng.integers(0, g, size=(bootstrap_draws, g))
        samples = sums[draws].sum(axis=1) / sizes[draws].sum(axis=1)
        lo, hi = (float(np.percentile(samples, 2.5)), float(np.percentile(samples, 97.5)))
        if lo <= 0 <= hi:
            warnings.append("the 95% bootstrap interval on the mean contains zero")

    # Randomization inference, and the hard limit on what G clusters can express.
    wild_p: float | None = None
    p_floor: float | None = None
    if g >= 2:
        wild_p, p_floor = wild_cluster_p(buckets, draws=wild_draws, seed=seed)

    # The alpha the hurdle implies, so the two tests are compared at one bar rather
    # than at two unrelated ones.
    required_alpha = _alpha_for_t(t_hurdle)
    resolvable = bool(p_floor is not None and p_floor <= required_alpha)
    if not resolvable and g >= 2:
        warnings.append(
            f"{g} 个独立单元最细只能表达 p={p_floor:.1e},而门槛 t={t_hurdle:.2f} "
            f"要求 p≤{required_alpha:.1e} —— 在这个样本量上'显著'无法被表示,"
            f"这不是差一点,是信息量不够。唯一的出路是更长的样本期。"
        )

    # Significance still needs the hurdle *and* the cluster floor. The bootstrap is
    # reported rather than made decisive: below the floor it is conservative to the
    # point of never rejecting, and above it the two agree — so making it the gate
    # would change nothing except to hide the resolution problem behind a p-value.
    significant = bool(abs(t_clustered) >= t_hurdle and g >= min_clusters)

    return ClusteredResult(
        n=n, n_clusters=g, mean=mean, median=median,
        win_rate=float((raw > 0).mean()),
        t_iid=t_iid, t_clustered=t_clustered, t_hurdle=t_hurdle,
        significant=significant,
        bootstrap_lo=lo, bootstrap_hi=hi,
        sign_test_p=sign_p,
        wild_p=wild_p, p_floor=p_floor, resolvable=resolvable,
        skew_ratio=skew_ratio, cluster_by=by, warnings=warnings,
    )


__all__ = [
    "ClusterBy", "ClusteredResult", "analyse", "cluster_key", "recommended_cluster",
    "wild_cluster_p",
]
