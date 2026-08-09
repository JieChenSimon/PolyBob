"""Sizing must come from the measured edge and a real account, or not at all.

Two defects motivated this module. The product printed an allocation derived from
a hardcoded ``capital=100_000`` — a fabricated number in the one field that moves
money. And ``libs/quant/position_sizing.py`` held Kelly with zero callers, because
there was no account for it to size against and no measured edge to size from.
"""

from __future__ import annotations

import pytest

from libs.portfolio.account import (
    MAX_DOMAIN_FRACTION,
    MAX_POSITION_FRACTION,
    Account,
    AccountNotConfigured,
    Position,
)
from libs.portfolio.sizing import (
    EdgeStatistics,
    kelly_fraction,
    size_position,
    win_rate_lower_bound,
)

# The two real edges, as the board measures them.
US = EdgeStatistics(win_rate=0.532, mean_excess=0.0511, n_clusters=9, win_loss_ratio=1.8)
ALT = EdgeStatistics(win_rate=0.706, mean_excess=0.0313, n_clusters=13, win_loss_ratio=2.1)


# ------------------------------------------------------ no account, no amount
def test_an_unconfigured_account_yields_a_fraction_but_no_money():
    """The rule is knowable without an account; the amount is not.

    This is the fix for the hardcoded 100,000: a person with no equity entered
    still learns "one tenth of capital", and never sees a share count computed
    from an account that does not exist.
    """
    d = size_position(US, Account(), domain="us_equity", entry_price=50.0, stop_price=45.0)
    assert d.fraction > 0
    assert d.amount is None and d.shares is None
    assert d.to_dict()["capital_known"] is False


def test_requiring_equity_on_an_empty_account_raises_rather_than_defaults():
    with pytest.raises(AccountNotConfigured, match="未配置"):
        Account().require_equity()


def test_zero_equity_is_unconfigured_not_a_zero_position():
    assert Account(equity=0.0).configured is False


# ------------------------------------------------------------------- Kelly
def test_kelly_is_zero_for_a_losing_edge():
    """A negative Kelly is not an instruction to reverse.

    The direction was pre-registered. A result pointing the other way falsified
    the hypothesis; trading it backwards is the data snooping the project already
    caught itself doing once.
    """
    losing = EdgeStatistics(win_rate=0.30, mean_excess=-0.02, n_clusters=40, win_loss_ratio=1.0)
    assert kelly_fraction(losing) == 0.0
    d = size_position(losing, Account(equity=10_000.0), domain="x")
    assert d.allowed is False
    assert d.binding_constraint == "negative_edge"


def test_an_unmeasured_payoff_ratio_cannot_flatter_the_size():
    """Unknown falls back to 1:1, which needs a win rate above 50% to size at all."""
    unknown = EdgeStatistics(win_rate=0.52, mean_excess=0.01, n_clusters=40)
    assert unknown.payoff_ratio == 1.0
    assert kelly_fraction(unknown) == pytest.approx(0.04, abs=1e-9)


def test_a_coin_flip_at_even_odds_gets_nothing():
    even = EdgeStatistics(win_rate=0.50, mean_excess=0.0, n_clusters=40, win_loss_ratio=1.0)
    assert kelly_fraction(even) == 0.0


# ------------------------------------------- estimation error, in the right place
def test_the_correction_goes_into_the_win_rate_not_onto_kellys_answer():
    """The bug this replaced.

    The first version multiplied Kelly's *output* by ``sqrt(n/20)``, and the
    archived ``kelly_with_estimation_error`` used ``1/(1+variance)`` the same way.
    Both shrink a number computed from a win rate nobody should have taken at face
    value. The correction belongs on the input: bet the lower confidence bound.
    """
    d = size_position(US, Account(equity=50_000.0), domain="x", entry_price=50.0)
    # 53.2% measured over 9 independent months could comfortably be 37%.
    assert d.win_rate_used < US.win_rate
    assert d.win_rate_used == pytest.approx(win_rate_lower_bound(0.532, 9))
    # And Kelly evaluated there is an order of magnitude smaller.
    assert d.kelly_prudent < d.kelly_point / 5


def test_the_lower_bound_tightens_as_independent_sample_grows():
    """More evidence, less pessimism — and the two must converge."""
    bounds = [win_rate_lower_bound(0.532, n) for n in (9, 20, 40, 200)]
    assert bounds == sorted(bounds)                 # monotonically rising
    assert bounds[-1] < 0.532                       # never exceeds the estimate
    assert bounds[-1] > 0.49                        # but approaches it


def test_the_bound_uses_independent_clusters_not_the_raw_event_count():
    """245 events in 13 weeks is thirteen observations in a large-n disguise."""
    assert win_rate_lower_bound(0.706, 13) < win_rate_lower_bound(0.706, 245)


def test_the_bound_stays_inside_zero_and_one():
    """Why Wilson and not ``p +/- z*sqrt(p(1-p)/n)``.

    The normal approximation misbehaves exactly where this project lives: small n
    and rates far from 50%. At p=1.0 it gives a zero-width interval, which would
    say a 3-for-3 edge is certain.
    """
    assert 0.0 <= win_rate_lower_bound(1.0, 3) < 1.0
    assert win_rate_lower_bound(0.0, 3) == 0.0
    assert win_rate_lower_bound(0.5, 0) == 0.0


def test_no_independent_sample_means_no_position():
    none_at_all = EdgeStatistics(win_rate=0.9, mean_excess=0.5, n_clusters=0, win_loss_ratio=3.0)
    d = size_position(none_at_all, Account(equity=10_000.0), domain="x")
    assert d.fraction == 0.0


def test_an_edge_that_vanishes_at_its_lower_bound_gets_nothing():
    """"Might be real, but the sample cannot support a bet" is a distinct verdict.

    It needs its own answer because the remedy differs: extend the sample period,
    rather than abandon the hypothesis.
    """
    thin = EdgeStatistics(win_rate=0.55, mean_excess=0.01, n_clusters=4, win_loss_ratio=1.0)
    d = size_position(thin, Account(equity=50_000.0), domain="x")
    assert d.allowed is False
    assert d.binding_constraint == "no_edge_at_lower_bound"
    assert d.kelly_point > 0                       # the point estimate looked fine
    assert any("延长样本期" in r for r in d.reasons_zh)


# ------------------------------------------------------------------ the cap
def test_the_two_real_edges_now_receive_different_sizes():
    """The defect worth fixing: they used to get identical fractions.

    Both suggested more than the cap on their point estimates, so the cap bound
    for both and a 53.2% win rate over 9 months was sized like a 70.6% one over 13
    weeks. On the lower bound the US edge collapses to ~2% while the altcoin edge
    still reaches the cap — a difference of more than four times, driven by how
    much evidence each one actually has.
    """
    us = size_position(US, Account(equity=50_000.0), domain="x", entry_price=50.0)
    alt = size_position(ALT, Account(equity=50_000.0), domain="y", entry_price=50.0)
    assert us.fraction < alt.fraction / 4
    assert us.binding_constraint == "kelly_on_lower_bound"
    assert alt.binding_constraint == "max_position_cap"


def test_the_cap_still_binds_a_genuinely_strong_edge():
    """Even on the lower bound, 70% with 2:1 suggests a third of the account."""
    d = size_position(ALT, Account(equity=50_000.0), domain="x", entry_price=50.0)
    assert d.kelly_prudent > MAX_POSITION_FRACTION
    assert d.fraction == pytest.approx(MAX_POSITION_FRACTION)


def test_sizing_grows_only_by_earning_it():
    """Hold the win rate fixed, extend the sample, and the size rises.

    This is the incentive the product should create: the way to a bigger position
    is more evidence, never a looser threshold.
    """
    sizes = [
        size_position(
            EdgeStatistics(win_rate=0.532, mean_excess=0.0511, n_clusters=n,
                           win_loss_ratio=1.8),
            Account(equity=50_000.0), domain="x", entry_price=50.0,
        ).fraction
        for n in (9, 15, 20)
    ]
    assert sizes == sorted(sizes)
    assert sizes[0] < MAX_POSITION_FRACTION


# --------------------------------------------------------------- the budgets
def test_the_domain_budget_stops_three_bets_becoming_one():
    """Three simultaneous US longs are one bet on US equities."""
    equity = 100_000.0
    held = [
        Position(f"S{i}", "us_equity", "e", "long", 100, 100.0, 90.0, "2026-08-01")
        for i in range(2)
    ]
    account = Account(equity=equity, positions=held)     # 20% already in us_equity
    # A strong edge, so the domain budget rather than the lower bound is what binds.
    d = size_position(ALT, account, domain="us_equity", entry_price=100.0, stop_price=90.0)
    assert d.fraction == pytest.approx(MAX_DOMAIN_FRACTION - 0.20)
    assert d.binding_constraint == "domain_budget"


def test_a_full_domain_leaves_no_room():
    equity = 100_000.0
    held = [Position("S", "us_equity", "e", "long", 250, 100.0, 90.0, "2026-08-01")]
    account = Account(equity=equity, positions=held)     # 25% = the whole budget
    d = size_position(ALT, account, domain="us_equity", entry_price=100.0, stop_price=90.0)
    assert d.fraction == 0.0
    assert d.allowed is False


def test_cross_domain_risk_does_not_diversify_to_zero():
    """A US long and an altcoin short lose together in a risk-asset selloff.

    Summing their risk as if independent is what makes two bets pointing the same
    way look like a hedge, so the default correlation is 0.5, not 0.
    """
    account = Account(equity=100_000.0, positions=[
        Position("AAPL", "us_equity", "e", "long", 100, 100.0, 90.0, "2026-08-01"),
        Position("SOL-USDT", "altcoin", "e", "short", 100, 100.0, 110.0, "2026-08-01"),
    ])
    independent = (1_000.0 ** 2 + 1_000.0 ** 2) ** 0.5     # ~1414 if uncorrelated
    assert account.correlated_risk() > independent
    assert account.correlated_risk(correlation=0.0) == pytest.approx(independent)


def test_a_position_without_a_stop_counts_as_fully_at_risk():
    """No stop is unmeasured risk, not zero risk.

    A position with no exit plan can lose its whole notional, and treating the
    missing number as 0 would let the risk budget be gamed by omitting a stop.
    """
    account = Account(equity=100_000.0, positions=[
        Position("X", "us_equity", "e", "long", 100, 100.0, None, "2026-08-01"),
    ])
    assert account.total_risk() == pytest.approx(10_000.0)
    assert account.snapshot()["positions_without_stop"] == 1


def test_a_missing_stop_is_flagged_in_the_reasoning():
    d = size_position(US, Account(equity=50_000.0), domain="x", entry_price=50.0)
    assert any("没有止损价" in r for r in d.reasons_zh)


# ------------------------------------------------------------- transparency
def test_every_decision_shows_its_working():
    """"Buy 340 shares" is unauditable; the chain that produced it is not."""
    d = size_position(US, Account(equity=50_000.0), domain="us_equity",
                      entry_price=50.0, stop_price=45.0)
    assert len(d.reasons_zh) >= 2
    assert any("Kelly" in r for r in d.reasons_zh)
    assert any("独立单元" in r for r in d.reasons_zh)
    payload = d.to_dict()
    # Both Kellys travel with the answer: the gap between them *is* the evidence
    # quality, and hiding the optimistic one hides where the difference came from.
    assert payload["kelly_point"] > payload["kelly_prudent"]
    assert payload["win_rate_used"] < US.win_rate


def test_the_snapshot_reports_none_not_zero_when_equity_is_unknown():
    """0% at risk would read as a measurement of safety."""
    assert Account().snapshot()["risk_fraction"] is None
    assert Account(equity=1_000.0).snapshot()["risk_fraction"] == 0.0
