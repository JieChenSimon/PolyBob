"""Reproducibility tests for the simulated backtest executor."""
import asyncio
from datetime import datetime

from libs.backtest.execution import ExecutionConfig, MarketState, SimulatedExecutor
from libs.schemas import Side


def _market_state() -> MarketState:
    return MarketState(
        best_bid=0.48,
        best_ask=0.52,
        bid_depth=5000.0,
        ask_depth=5000.0,
        timestamp=datetime(2026, 1, 1, 12, 0, 0),
    )


def _run(seed, n=8):
    config = ExecutionConfig(base_latency_ms=1.0, latency_std_ms=0.5, seed=seed)
    executor = SimulatedExecutor(config)

    async def _execute_all():
        results = []
        for i in range(n):
            execution = await executor.execute_order(
                order_id=f"order_{i}",
                market_id="mkt_btc",
                side=Side.BUY_YES,
                price=0.52,
                size=10.0 + i,
                market_state=_market_state(),
            )
            results.append(execution)
        return results

    return asyncio.run(_execute_all())


def test_same_seed_produces_identical_fills_and_latencies():
    first = _run(seed=123)
    second = _run(seed=123)

    assert len(first) == len(second) == 8
    for a, b in zip(first, second):
        assert a is not None and b is not None
        assert a.price == b.price
        assert a.size == b.size
        assert a.slippage == b.slippage
        assert a.latency_ms == b.latency_ms


def test_different_seeds_produce_different_latencies():
    first = _run(seed=123)
    second = _run(seed=456)

    assert [e.latency_ms for e in first] != [e.latency_ms for e in second]


def test_default_config_is_seeded_and_deterministic():
    # Default ExecutionConfig carries a fixed seed so default backtest runs
    # are reproducible; seed=None opts into nondeterminism.
    assert ExecutionConfig().seed is not None

    first = SimulatedExecutor()
    second = SimulatedExecutor()
    assert first._rng.random() == second._rng.random()


def test_seeded_executor_never_touches_global_rng():
    import random

    random.seed(999)
    before = random.getstate()
    _run(seed=123)
    assert random.getstate() == before
