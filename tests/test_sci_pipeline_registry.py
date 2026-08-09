"""P8b — simulation runs are logged to the experiment registry.

Proves the round-trip: creating and finalizing a sim run writes reproducible
records (params + versions, then metrics) that are queryable from the registry.
"""

from __future__ import annotations

import asyncio

from libs.research.registry import ExperimentRegistry
from modules.simulation.service import SimulationService


def _service(tmp_path):
    registry = ExperimentRegistry(tmp_path / "reg.sqlite3", capture_git=False)
    service = SimulationService(
        tmp_path / "sim.sqlite3", equity_poll_seconds=3600, registry=registry
    )
    return service, registry


def test_created_and_finalized_run_round_trip(tmp_path):
    service, registry = _service(tmp_path)

    async def scenario() -> str:
        run = await service.create_run(
            name="reg-test",
            strategy_id="spread_reversion_v1",
            universe=["m1", "m2"],
            initial_capital=1000.0,
            config={"spread_threshold_bps": 120.0},
        )
        run_id = run["run_id"]
        await service.stop_run(run_id)  # paused -> stopped triggers final log
        return run_id

    run_id = asyncio.run(scenario())

    created = registry.get_run(f"{run_id}:created")
    assert created is not None
    assert created.experiment == "simulation"
    assert created.params["strategy_id"] == "spread_reversion_v1"
    assert created.params["config"]["spread_threshold_bps"] == 120.0
    assert created.model_version == "spread_reversion_v1"
    assert created.data_version is not None
    assert "created" in created.tags

    final = registry.get_run(f"{run_id}:final")
    assert final is not None
    # metrics are numeric-only and include the run summary counters
    assert "trade_count" in final.metrics
    assert isinstance(final.metrics["trade_count"], float)
    assert "final" in final.tags

    # queryable together, newest first
    runs = registry.list_runs("simulation")
    assert {r.run_id for r in runs} >= {f"{run_id}:created", f"{run_id}:final"}


def test_metrics_are_scalar_only(tmp_path):
    """The registry stores float metrics; the non-scalar ``per_instrument``
    dict from compute_run_metrics must be filtered out, not crash logging."""
    service, registry = _service(tmp_path)

    async def scenario() -> str:
        run = await service.create_run(
            name="scalar-test",
            strategy_id="momentum_dualma_v1",
            universe=["m1"],
            initial_capital=500.0,
        )
        await service.stop_run(run["run_id"])
        return run["run_id"]

    run_id = asyncio.run(scenario())
    final = registry.get_run(f"{run_id}:final")
    assert final is not None
    assert all(isinstance(v, float) for v in final.metrics.values())
    assert "per_instrument" not in final.metrics
