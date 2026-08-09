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
