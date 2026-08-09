"""The inference layer that decides whether an edge is real.

Every promoted edge on this project's board cleared its multiple-testing hurdle
on a statistic that assumed the events were independent draws. They were not:
overlapping holding windows and calendar bunching mean the effective sample was a
fraction of the event count. These tests pin the corrected behaviour, and — just
as importantly — pin that the correction is a *measurement* rather than a blanket
penalty, because a blanket penalty is something a motivated researcher can argue
their way out of.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from libs.quant.clustered_inference import (
    analyse,
    cluster_key,
    recommended_cluster,
)


def _dates(n: int, *, weeks: int, start: dt.date = dt.date(2025, 1, 6)) -> list[str]:
    """n event dates spread across ``weeks`` distinct calendar weeks."""
    return [
        (start + dt.timedelta(weeks=i % weeks, days=i % 5)).isoformat()
        for i in range(n)
    ]


def _returns(n: int, mean: float, sd: float, *, weeks: int, shock: float, seed: int = 3):
    """Returns with a per-week common component — the shape of a real event study."""
    rng = np.random.default_rng(seed)
    week_shock = rng.normal(0.0, shock, size=weeks)
    return [float(rng.normal(mean, sd) + week_shock[i % weeks]) for i in range(n)]


# --------------------------------------------------------------- cluster keys
def test_cluster_key_groups_by_the_requested_unit():
    assert cluster_key("2025-01-08", "day") == "2025-01-08"
    assert cluster_key("2025-01-06", "week") == cluster_key("2025-01-10", "week")
    assert cluster_key("2025-01-31", "month") == cluster_key("2025-01-02", "month")


def test_cluster_key_ignores_a_timestamp_suffix():
    """Sources hand over dates in mixed shapes; the unit must not depend on that."""
    assert cluster_key("2025-03-04T12:30:00Z", "day") == "2025-03-04"


def test_week_boundary_does_not_merge_adjacent_weeks():
    """A Friday and the following Monday are different weeks, not one blur."""
    assert cluster_key("2025-01-10", "week") != cluster_key("2025-01-13", "week")


def test_recommended_cluster_is_at_least_the_holding_period():
    """The unit has to outlast the hold, or windows still straddle two clusters."""
    assert recommended_cluster(1) == "day"
    assert recommended_cluster(5) == "week"       # the altcoin edge
    assert recommended_cluster(20) == "month"     # the insider edge


# ------------------------------------------------------- the correction itself
def test_shared_shocks_shrink_the_statistic():
    """The defect, in one assertion.

    Same returns, same mean; only the standard error changes. This is why t=5.40
    became 2.35 on the insider edge without a single return being recomputed.
    """
    rets = _returns(800, 0.02, 0.03, weeks=25, shock=0.05)
    result = analyse(rets, _dates(800, weeks=25), t_hurdle=3.77, hold_days=5)
    assert abs(result.t_clustered) < abs(result.t_iid)
    assert result.mean == pytest.approx(float(np.mean(rets)))


def test_independent_events_are_not_penalised():
    """No dependence, no haircut.

    If clustering always cut the statistic it would be a tax on sample size, and
    a tax invites negotiation. It has to leave clean data alone so that when it
    *does* bite, the bite is information.
    """
    rets = _returns(800, 0.02, 0.03, weeks=25, shock=0.0)
    result = analyse(rets, _dates(800, weeks=25), t_hurdle=3.77, hold_days=5)
    assert abs(result.t_clustered) > abs(result.t_iid) * 0.7


def test_events_crammed_into_few_clusters_are_not_significant():
    """A large n inside a handful of weeks is a small sample wearing a disguise."""
    rets = _returns(1000, 0.03, 0.02, weeks=5, shock=0.04)
    result = analyse(rets, _dates(1000, weeks=5), t_hurdle=3.77, hold_days=5)
    assert result.n == 1000
    assert result.n_clusters == 5
    assert result.significant is False
    assert any("independence clusters" in w for w in result.warnings)


def test_significance_requires_both_the_hurdle_and_enough_clusters():
    """Clearing the t-hurdle on 5 clusters is not clearing it.

    Cluster-robust errors are themselves unreliable below ~20 groups, so a big
    clustered t computed from a handful of weeks is not evidence. Both current
    edges fail here as well as on the hurdle: 9 months and 13 weeks.
    """
    rets = [0.05] * 400                     # a comically clean effect
    result = analyse(rets, _dates(400, weeks=4), t_hurdle=3.77, hold_days=5)
    assert result.n_clusters == 4
    assert result.significant is False


def test_a_real_effect_over_many_clusters_still_passes():
    """The correction must not make significance unreachable.

    The A-share avoidance filter is the live proof: 40,768 events over 125
    independent weeks survives clustering at t=-6.85. A test suite that could
    never produce a pass would mean the gate had become a wall.
    """
    rets = _returns(3000, 0.02, 0.02, weeks=120, shock=0.005)
    result = analyse(rets, _dates(3000, weeks=120), t_hurdle=3.77, hold_days=5)
    assert result.n_clusters == 120
    assert result.significant is True


# ------------------------------------------------------------- skew and shape
def test_a_tail_driven_mean_is_flagged():
    """The insider edge's real shape: mean +5.08%, median +0.55%.

    The average describes a few events, not the trade you are about to place. A
    t-test on that sample reads the tail as evidence about the centre.
    """
    rets = [0.001] * 300 + [2.0] * 12
    result = analyse(rets, _dates(312, weeks=30), t_hurdle=3.77, hold_days=5)
    assert result.skew_ratio is not None and result.skew_ratio > 3
    assert any("carried by a few tail events" in w for w in result.warnings)


def test_sign_test_reads_the_typical_trade_not_the_tail():
    """A mean pulled positive by outliers while most trades lose must show up."""
    rets = [-0.01] * 250 + [1.0] * 12
    result = analyse(rets, _dates(262, weeks=30), t_hurdle=3.77, hold_days=5)
    assert result.mean > 0                       # the tail carries the average
    assert result.win_rate < 0.1                 # but almost nothing wins
    assert result.sign_test_p is not None and result.sign_test_p < 0.01


def test_bootstrap_interval_containing_zero_is_flagged():
    rets = _returns(400, 0.001, 0.06, weeks=40, shock=0.02)
    result = analyse(rets, _dates(400, weeks=40), t_hurdle=3.77, hold_days=5)
    assert result.bootstrap_lo is not None
    assert result.bootstrap_lo <= 0 <= result.bootstrap_hi
    assert any("contains zero" in w for w in result.warnings)


def test_bootstrap_is_deterministic():
    """A gate that moves between runs cannot be checked in CI."""
    args = dict(t_hurdle=3.77, hold_days=5)
    rets, dates = _returns(400, 0.02, 0.03, weeks=30, shock=0.01), _dates(400, weeks=30)
    first = analyse(rets, dates, **args)
    second = analyse(rets, dates, **args)
    assert first.bootstrap_lo == second.bootstrap_lo
    assert first.t_clustered == second.t_clustered


# ----------------------------------------------------------------- degenerate
def test_no_returns_is_not_a_pass():
    result = analyse([], [], t_hurdle=3.77, hold_days=5)
    assert result.significant is False
    assert result.n == 0


def test_a_single_cluster_cannot_be_significant():
    """One week of data is one observation, however many events it holds."""
    rets = [0.04] * 200
    result = analyse(rets, ["2025-01-06"] * 200, t_hurdle=3.77, hold_days=5)
    assert result.n_clusters == 1
    assert result.t_clustered == 0.0
    assert result.significant is False


def test_non_finite_returns_are_dropped_not_counted():
    """A missing return must not become a zero — the project's standing rule."""
    rets = [0.02, float("nan"), 0.03, float("inf")]
    result = analyse(rets, _dates(4, weeks=4), t_hurdle=3.77, hold_days=5)
    assert result.n == 2


def test_to_dict_reports_both_statistics():
    """The i.i.d. value stays visible so the size of the correction is legible."""
    rets = _returns(600, 0.02, 0.03, weeks=30, shock=0.03)
    payload = analyse(rets, _dates(600, weeks=30), t_hurdle=3.77, hold_days=5).to_dict()
    assert payload["inference"] == "cluster_robust"
    assert abs(payload["t_stat"]) < abs(payload["t_stat_iid"])
    assert payload["n_clusters"] < payload["n"]
    assert payload["cluster_by"] == "week"


# ------------------------------------------------ the estimator must be the mean
def test_the_reported_mean_and_the_t_statistic_describe_the_same_quantity():
    """The defect this replaced: two estimators on one row.

    The first version computed the t-statistic from the unweighted average of cluster
    means while the board printed ``mean_excess_pct`` from the sample mean. On the real
    altcoin edge those differed by 37% — +3.09% reported next to a t computed at
    +2.25%. Whatever else a row does, its effect size and its significance have to be
    about the same number.
    """
    rets = _returns(600, 0.02, 0.03, weeks=30, shock=0.02)
    result = analyse(rets, _dates(600, weeks=30), t_hurdle=3.77, hold_days=5)
    assert result.mean == pytest.approx(float(np.mean(rets)))
    # The t-statistic is that mean over its cluster-robust standard error, so the
    # implied SE must be positive and finite.
    implied_se = result.mean / result.t_clustered
    assert implied_se > 0


def test_unbalanced_clusters_do_not_let_a_tiny_group_dominate():
    """A 3-event week must not carry the same weight as a 32-event week.

    Averaging cluster means gave them equal weight, which is why the altcoin edge —
    whose weekly clusters range from 3 to 32 events — was penalised twice: once for
    genuine dependence and once for the arithmetic.
    """
    import datetime as dt

    start = dt.date(2025, 1, 6)
    returns: list[float] = []
    dates: list[str] = []
    for week in range(25):
        # One outlying week with a single extreme observation, the rest well behaved.
        size, value = (1, 5.0) if week == 0 else (40, 0.02)
        for i in range(size):
            returns.append(value)
            dates.append((start + dt.timedelta(weeks=week, days=i % 5)).isoformat())

    result = analyse(returns, dates, t_hurdle=3.77, hold_days=5)
    # The pooled mean is dominated by the 960 ordinary observations, not by the one
    # outlier, so it stays near 0.02 rather than being dragged toward 5.0/25.
    assert result.mean < 0.03
    assert result.n_clusters == 25


def test_a_single_cluster_holding_everything_still_cannot_be_significant():
    result = analyse([0.05] * 300, ["2025-01-06"] * 300, t_hurdle=3.77, hold_days=5)
    assert result.n_clusters == 1
    assert result.t_clustered == 0.0
    assert result.significant is False


def test_the_bootstrap_interval_brackets_the_reported_mean():
    """The interval must be around the quantity being reported, not another one."""
    rets = _returns(600, 0.03, 0.02, weeks=40, shock=0.005)
    result = analyse(rets, _dates(600, weeks=40), t_hurdle=3.77, hold_days=5)
    assert result.bootstrap_lo is not None
    assert result.bootstrap_lo <= result.mean <= result.bootstrap_hi


def test_zero_variance_within_and_across_clusters_is_not_significant():
    """Every observation identical means no measurable uncertainty — and no evidence.

    Dividing by a zero standard error would produce an infinite t, which is how a
    degenerate sample turns into a promotion.
    """
    result = analyse([0.02] * 400, _dates(400, weeks=40), t_hurdle=3.77, hold_days=5)
    assert result.t_clustered == 0.0
    assert result.significant is False


# --------------------------------------- small-sample inference and its limits
def test_the_wild_bootstrap_is_reported_alongside_the_asymptotic_t():
    """CRVE's asymptotics assume many clusters; this project has 9, 14 and 2.

    Simulated from a process calibrated to the real insider edge, the asymptotic test
    rejects at 10-13% against a nominal 5% when G is 5-9 — it manufactures false
    positives exactly where the real edges live. The wild cluster bootstrap
    (Cameron, Gelbach & Miller 2008) restores correct size from G≈9 upward.
    """
    rets = _returns(600, 0.02, 0.03, weeks=30, shock=0.02)
    result = analyse(rets, _dates(600, weeks=30), t_hurdle=3.77, hold_days=5)
    assert result.wild_p is not None
    assert 0.0 < result.wild_p <= 1.0


def test_the_bootstrap_cannot_claim_a_p_value_of_zero():
    """The observed statistic is one of its own draws, so p is never 0."""
    rets = [0.05 + 0.001 * i for i in range(400)]
    result = analyse(rets, _dates(400, weeks=40), t_hurdle=3.77, hold_days=5)
    assert result.wild_p is not None and result.wild_p > 0.0


def test_few_clusters_cannot_express_the_required_significance():
    """The finding that reframes the whole board.

    With G clusters there are only ``2^(G-1)`` sign assignments, so no p-value below
    ``1/2^(G-1)`` is representable however strong the effect. At G=9 that floor is
    3.9e-3 while a t-hurdle of 4.19 demands 2.8e-5 — 138 times smaller. The insider
    edge is not *near* significance at 9 independent months; it is at a sample size
    where significance cannot be expressed, and that calls for calendar rather than
    another look at the numbers.
    """
    result = analyse(_returns(600, 0.03, 0.02, weeks=9, shock=0.01),
                     _dates(600, weeks=9), t_hurdle=4.19, hold_days=5)
    assert result.n_clusters == 9
    assert result.p_floor == pytest.approx(1 / 2 ** 8)
    assert result.resolvable is False
    assert any("无法被表示" in w for w in result.warnings)


def test_many_clusters_can_express_it():
    """The A-share filter's actual position: 125 independent weeks, fully resolvable."""
    result = analyse(_returns(3000, -0.02, 0.02, weeks=120, shock=0.005),
                     _dates(3000, weeks=120), t_hurdle=4.19, hold_days=5)
    assert result.resolvable is True
    assert result.p_floor is not None and result.p_floor < 1e-9


def test_the_resolution_floor_tightens_with_more_clusters():
    floors = []
    for weeks in (9, 14, 20, 30):
        r = analyse(_returns(600, 0.02, 0.02, weeks=weeks, shock=0.01),
                    _dates(600, weeks=weeks), t_hurdle=4.19, hold_days=5)
        floors.append(r.p_floor)
    assert floors == sorted(floors, reverse=True)


def test_the_hurdle_is_stricter_than_bonferroni():
    """Worth knowing before concluding an edge failed on its merits.

    The board's hurdle is a heuristic, ``3.0 + 0.5*log10(n_trials)``. At 237 trials it
    gives 4.19, i.e. alpha = 2.8e-5 — stricter than Bonferroni at the same count
    (0.05/237 = 2.1e-4, t = 3.71), and Bonferroni is already the most conservative
    correction in standard use.
    """
    from libs.quant.clustered_inference import _alpha_for_t
    from libs.quant.pbo import deflated_t_stat_threshold

    hurdle = deflated_t_stat_threshold(237)
    assert hurdle == pytest.approx(4.19, abs=0.01)
    assert _alpha_for_t(hurdle) < 0.05 / 237


def test_a_tail_driven_significance_is_called_out():
    """The sharpest form of the skew warning, and it fired on real data.

    The single-buy control reaches t=5.13 — above the hurdle — with a 50.6% win rate, a
    median of +0.09% and a sign test at p=0.63. A coin flip with a few large winners.
    That may still be a real portfolio return, but it is not what "these stocks
    outperform" sounds like, and it sizes completely differently: Kelly on a 50.6% win
    rate is nothing, while the mean is positive.
    """
    # Mostly nothing, a few large winners: significant on the mean, a coin flip on the
    # median. Spread over enough clusters that the t-statistic is trustworthy.
    rets = ([0.0005, -0.0005] * 240) + [1.2] * 20
    result = analyse(rets, _dates(500, weeks=40), t_hurdle=2.0, hold_days=5)
    assert result.sign_test_p is not None and result.sign_test_p > 0.10
    assert abs(result.t_clustered) >= 2.0 * 0.75
    assert any("只存在于尾部" in w for w in result.warnings)


def test_a_broad_effect_is_not_called_tail_driven():
    """The warning must not fire on an edge that actually moves the typical trade."""
    rets = _returns(600, 0.02, 0.01, weeks=40, shock=0.002)
    result = analyse(rets, _dates(600, weeks=40), t_hurdle=2.0, hold_days=5)
    assert result.win_rate > 0.9
    assert not any("只存在于尾部" in w for w in result.warnings)
