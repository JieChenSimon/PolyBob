"""Tests for the scientific-method guardrails: pre-registration and PBO."""

from __future__ import annotations

import numpy as np
import pytest

from libs.quant.hypothesis import (
    Hypothesis,
    HypothesisRegistry,
    InadmissibleHypothesis,
    Rationale,
)
from libs.quant.pbo import (
    deflated_t_stat_threshold,
    probability_of_backtest_overfitting,
)


def _valid(**overrides):
    base = dict(
        hypothesis_id="momentum_xs",
        claim="Winners keep winning over 1-12 months because investors underreact to news.",
        rationale=Rationale.BEHAVIOURAL,
        mechanism="Underreaction plus limits to arbitrage (career risk in long drawdowns).",
        literature="Replicates across markets and asset classes; survives costs at scale.",
        direction="long_winners_short_losers",
        universe="OKX USDT spot",
        horizon_days=30,
        cost_bps=10.0,
    )
    base.update(overrides)
    return Hypothesis(**base)


# --- pre-registration ------------------------------------------------------


def test_hypothesis_without_economic_rationale_is_rejected():
    # This is exactly what range_contraction was: a chart pattern, no theory.
    with pytest.raises(InadmissibleHypothesis):
        _valid(hypothesis_id="range_contraction", rationale=Rationale.NONE)


def test_hypothesis_requires_a_mechanism():
    with pytest.raises(InadmissibleHypothesis):
        _valid(mechanism="   ")


def test_hypothesis_claim_must_be_short():
    with pytest.raises(InadmissibleHypothesis):
        _valid(claim="A. B. C. D. E. F.")   # a page of rules => overfit


def test_valid_hypothesis_registers():
    h = _valid()
    assert h.rationale is Rationale.BEHAVIOURAL
    assert h.direction == "long_winners_short_losers"


def test_registry_counts_every_trial(tmp_path):
    reg = HypothesisRegistry(tmp_path / "reg.json")
    reg.register(_valid(hypothesis_id="h1"))
    reg.register(_valid(hypothesis_id="h2"))
    assert reg.n_trials == 2

    reg.record_result("h1", {"sharpe": 0.4, "approved": False})
    reloaded = HypothesisRegistry(tmp_path / "reg.json")
    assert reloaded.n_trials == 2
    entry = next(e for e in reloaded.entries if e["hypothesis"]["hypothesis_id"] == "h1")
    assert entry["result"]["approved"] is False


def test_abandoned_searches_still_count_as_trials(tmp_path):
    """A search you ran and discarded consumed a draw from the same distribution.

    The real omission: a 184-configuration chart-pattern sweep and an 18-test
    directional board were both run, both found nothing, and neither reached the
    registry — so the hurdle was computed as if 35 trials had happened when the
    honest figure was 237 (3.77 vs 4.19). Forgetting a failed search is the one
    kind of forgetting that makes your own results look better.
    """
    reg = HypothesisRegistry(tmp_path / "reg.json")
    reg.register(_valid(hypothesis_id="h1"))
    assert reg.n_trials == 1

    reg.record_search("wide_sweep", 184, "chart patterns", outcome="0 promoted")
    assert reg.n_trials == 185


def test_a_search_survives_a_reload(tmp_path):
    """The failure mode this guards: trials that quietly evaporate.

    ``_collapse_duplicates`` keys entries by ``hypothesis_id``. A search row has
    none, so a naive filter drops it on load — the count would be right in the
    process that wrote it and wrong in every process that read it afterwards,
    lowering the bar for whoever came next.
    """
    reg = HypothesisRegistry(tmp_path / "reg.json")
    reg.record_search("wide_sweep", 184, "chart patterns")
    reg.register(_valid(hypothesis_id="h1"))

    reloaded = HypothesisRegistry(tmp_path / "reg.json")
    assert reloaded.n_trials == 185
    assert [s["search_id"] for s in reloaded.searches] == ["wide_sweep"]


def test_recording_a_search_twice_does_not_double_count(tmp_path):
    """Re-running the sweep script must not inflate the count either."""
    reg = HypothesisRegistry(tmp_path / "reg.json")
    reg.record_search("wide_sweep", 184, "chart patterns")
    reg.record_search("wide_sweep", 184, "chart patterns")
    assert reg.n_trials == 184


def test_searches_are_never_claimed_as_evidence(tmp_path):
    """They raise the bar; they never count as a tested hypothesis."""
    reg = HypothesisRegistry(tmp_path / "reg.json")
    reg.record_search("wide_sweep", 184, "chart patterns")
    assert reg.untested == []                    # not a pre-registered hypothesis
    assert reg.result_for("wide_sweep") is None


def test_the_live_registry_counts_the_prior_searches():
    """The committed registry must hold both backfilled sweeps.

    If this fails, ``data/hypothesis_registry.json`` lost them and every hurdle in
    the repository just got easier. Backfilled by
    ``scripts/register_prior_searches.py``.
    """
    reg = HypothesisRegistry()
    ids = {s["search_id"] for s in reg.searches}
    assert {"wide_chart_pattern_sweep", "focused_directional_board"} <= ids
    assert reg.n_trials >= 237


# --- PBO -------------------------------------------------------------------


def test_pbo_high_for_pure_noise():
    # Random configs: selecting the in-sample best should not help out-of-sample,
    # so PBO must be far from 0 (near a coin flip).
    rng = np.random.default_rng(0)
    matrix = rng.normal(0, 0.01, (20, 600))
    result = probability_of_backtest_overfitting(matrix, n_blocks=10)
    assert 0.0 <= result.pbo <= 1.0
    assert result.pbo > 0.25          # noise selection is not credible
    assert result.verdict in {"suspect", "overfit"}


def test_pbo_low_when_one_config_is_genuinely_better():
    rng = np.random.default_rng(1)
    matrix = rng.normal(0.0, 0.01, (10, 600))
    matrix[3] = rng.normal(0.004, 0.01, 600)     # a real, persistent edge
    result = probability_of_backtest_overfitting(matrix, n_blocks=10)
    assert result.pbo < 0.10
    assert result.verdict == "credible"


def test_pbo_requires_multiple_configs():
    with pytest.raises(ValueError):
        probability_of_backtest_overfitting(np.zeros((1, 500)))


def test_t_threshold_rises_with_trials():
    assert deflated_t_stat_threshold(1) == 3.0
    assert deflated_t_stat_threshold(100) > deflated_t_stat_threshold(10) > 3.0
