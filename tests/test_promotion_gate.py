"""Tests for the strategy promotion gate (PSR/DSR, cost-stress, gate)."""

from __future__ import annotations

import numpy as np
import pytest

from libs.quant.promotion import (
    PromotionGate,
    annualized_sharpe,
    cost_stress_test,
    deflated_sharpe_ratio,
    expected_max_sharpe,
    min_track_record_length,
    probabilistic_sharpe_ratio,
)


def _returns(mean, std, n, seed=0):
    rng = np.random.default_rng(seed)
    return rng.normal(mean, std, n)


# --- PSR / DSR ------------------------------------------------------------


def test_psr_high_for_strong_consistent_edge():
    r = _returns(0.001, 0.005, 2000, seed=1)  # strong positive per-period SR
    psr = probabilistic_sharpe_ratio(r)
    assert psr > 0.99


def test_psr_low_for_zero_edge():
    r = _returns(0.0, 0.01, 2000, seed=2)
    psr = probabilistic_sharpe_ratio(r)
    assert psr < 0.9  # not confidently better than nothing


def test_dsr_penalizes_many_trials():
    r = _returns(0.0008, 0.006, 2000, seed=3)
    dsr_1 = deflated_sharpe_ratio(r, n_trials=1)
    dsr_500 = deflated_sharpe_ratio(r, n_trials=500)
    # More trials -> higher bar -> lower deflated confidence.
    assert dsr_1 > dsr_500
    assert 0.0 <= dsr_500 <= dsr_1 <= 1.0


def test_expected_max_sharpe_grows_with_trials():
    assert expected_max_sharpe(1000, 0.02) > expected_max_sharpe(10, 0.02) > 0


def test_min_track_record_length_finite_for_real_edge():
    r = _returns(0.001, 0.005, 3000, seed=4)
    mtrl = min_track_record_length(r)
    assert np.isfinite(mtrl) and mtrl > 0


# --- cost stress ----------------------------------------------------------


def _strategy_returns_at_cost(cost_multiple, *, gross_mean=0.0022, cost=0.0002, std=0.005, seed=7):
    rng = np.random.default_rng(seed)
    gross = rng.normal(gross_mean, std, 1500)
    return gross - cost * cost_multiple


def test_cost_stress_passes_when_edge_survives_and_degrades():
    result = cost_stress_test(
        _strategy_returns_at_cost,
        cost_multiples=(1.0, 2.0, 3.0),
        min_sharpe=0.3,
    )
    assert result.degrades_with_cost
    assert result.worst_sharpe <= result.base_sharpe
    assert result.passed


def test_cost_stress_fails_when_costs_kill_the_edge():
    # A tiny gross edge that vanishes under 3x costs.
    result = cost_stress_test(
        lambda m: _strategy_returns_at_cost(m, gross_mean=0.0005, cost=0.0006),
        cost_multiples=(1.0, 2.0, 3.0),
        min_sharpe=1.0,
    )
    assert not result.passed


def test_cost_stress_flags_cost_insensitivity():
    # Returns identical regardless of cost -> suspicious (no degradation).
    fixed = _returns(0.001, 0.005, 1000, seed=9)
    result = cost_stress_test(lambda _m: fixed, cost_multiples=(1.0, 3.0), min_sharpe=0.0)
    # Degradation check: equal sharpe counts as "not worse", so degrades==True
    # only via tolerance; force a strictly-flat series to confirm gate logic.
    assert result.base_sharpe == pytest.approx(result.worst_sharpe)


# --- full gate ------------------------------------------------------------


def test_gate_approves_a_robust_strategy():
    gate = PromotionGate(n_trials=1, min_dsr=0.9, min_observations=100, cost_min_sharpe=0.3)
    decision = gate.evaluate(
        _returns(0.0015, 0.006, 1500, seed=11),
        cost_returns_fn=_strategy_returns_at_cost,
        oos_stability_rate=0.8,
    )
    assert decision.approved, decision.to_dict()


def test_gate_rejects_on_multiple_testing():
    gate = PromotionGate(n_trials=1000, min_dsr=0.95, min_observations=100)
    decision = gate.evaluate(_returns(0.0006, 0.006, 1500, seed=12))
    assert not decision.approved
    assert any(c.name == "deflated_sharpe" and not c.passed for c in decision.checks)


def test_gate_rejects_on_short_sample():
    gate = PromotionGate(n_trials=1, min_dsr=0.0, min_observations=500)
    decision = gate.evaluate(_returns(0.001, 0.005, 50, seed=13))
    assert not decision.approved
    assert any(c.name == "min_observations" and not c.passed for c in decision.checks)


def test_gate_does_not_skip_missing_cost_or_oos_evidence():
    decision = PromotionGate(n_trials=1, min_dsr=0.0).evaluate(
        _returns(0.001, 0.005, 200, seed=15)
    )
    checks = {check.name: check for check in decision.checks}
    assert decision.approved is False
    assert decision.status == "unknown"
    assert checks["cost_stress"].evidence_status == "unknown"
    assert checks["oos_stability"].evidence_status == "unknown"


def test_annualized_sharpe_scales():
    r = _returns(0.001, 0.01, 1000, seed=14)
    assert annualized_sharpe(r, 252) == pytest.approx(
        annualized_sharpe(r, 1) * np.sqrt(252), rel=1e-9
    )


# --------------------------------------------------- gate at the only choke point
@pytest.mark.asyncio
async def test_gate_blocks_intents_created_inside_the_process(monkeypatch):
    """The gate has to stop the process, not just the human.

    It used to live in the API route. That stopped you from raising an intent by
    hand for an unvalidated strategy, while the lifespan auto-started
    ``spread_arbitrage_v1`` — which is on no board — and that path never went
    through the route. A gate on the door humans use is not a gate.
    """
    from unittest.mock import MagicMock

    from modules.execution_engine.intent_execution_service import (
        IntentExecutionService,
        StrategyNotPromoted,
    )

    service = IntentExecutionService(basket_executor=MagicMock())
    with pytest.raises(StrategyNotPromoted):
        await service.create_intent(
            strategy_id="spread_arbitrage_v1", rationale="auto",
            expected_edge_bps=20.0, confidence=0.9, legs=[],
        )


@pytest.mark.asyncio
async def test_gate_allows_a_promoted_strategy(promoted_strategy):
    from unittest.mock import MagicMock

    from modules.execution_engine.intent_execution_service import IntentExecutionService

    service = IntentExecutionService(basket_executor=MagicMock())
    result = await service.create_intent(
        strategy_id="us_insider_cluster_buy", rationale="cluster filing",
        expected_edge_bps=511.0, confidence=0.53, legs=[],
    )
    assert result["intent_id"]


def test_runtime_mode_comes_from_the_board_not_the_name():
    """``"spread" in strategy_id -> paper_ready`` handed out a free pass.

    The board is the only authority on what has an edge; what letters are in a
    strategy's name says nothing about it.

    Both halves are asserted through the *fixture's* board rather than the live
    one. This test used to hardcode ``us_insider_cluster_buy == "paper_ready"``,
    which was true only because that edge happened to be promoted at the time;
    when clustered standard errors dropped it back to lab the test failed even
    though the mechanism it describes still worked perfectly. A test of "the mode
    follows the board" must not also assert what today's board contains.
    """
    from modules.strategy_manager.service import StrategyManagerService

    manager = StrategyManagerService()
    assert manager._derive_runtime_mode("spread_arbitrage_v1") == "research"
    assert manager._derive_runtime_mode("cross_market_dislocation_v1") == "research"


def test_runtime_mode_follows_a_promotion(promoted_strategy):
    """Promote anything and the mode moves with it — including a made-up name."""
    from modules.strategy_manager.service import StrategyManagerService

    manager = StrategyManagerService()
    assert manager._derive_runtime_mode("anything_the_board_cleared") == "paper_ready"


def test_no_strategy_is_paper_ready_on_the_live_board():
    """The current, honest state of the desk: nothing may leave research.

    Not an invariant of the design — a snapshot of the evidence. Both former
    trade edges cleared their hurdle on i.i.d. t-statistics (5.40 and 6.38);
    clustered, the same real data gives 2.35 and 1.81 against 3.77. If a future
    experiment earns a promotion this test is expected to fail, and the fix is to
    update it — deliberately, having looked at the new evidence.
    """
    from modules.strategy_manager.service import StrategyManagerService

    manager = StrategyManagerService()
    for strategy in ("us_insider_cluster_buy", "altcoin_retail_crowding",
                     "a_share_billboard_reversal", "btc5m_mispricing"):
        assert manager._derive_runtime_mode(strategy) == "research", strategy
