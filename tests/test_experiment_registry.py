"""Tests for the reproducibility experiment registry."""

from __future__ import annotations

import pytest

from libs.research.registry import ExperimentRegistry


@pytest.fixture
def registry(tmp_path):
    return ExperimentRegistry(tmp_path / "runs.sqlite3", capture_git=False)


def test_log_and_get_run_roundtrips(registry):
    record = registry.log_run(
        "spread_reversion",
        params={"position_fraction": 0.03, "mid_penalty_bps": 10.0},
        metrics={"sharpe": 1.8, "max_drawdown": 0.12},
        data_version="2026-07-01",
        model_version="v1",
        tags=["lab"],
        notes="first pass",
    )
    fetched = registry.get_run(record.run_id)
    assert fetched is not None
    assert fetched.params["position_fraction"] == 0.03
    assert fetched.metrics["sharpe"] == 1.8
    assert fetched.data_version == "2026-07-01"
    assert fetched.tags == ["lab"]


def test_runs_are_reproducible_by_versions(registry):
    record = registry.log_run(
        "fusion",
        params={"seed": 42},
        metrics={"sharpe": 2.0},
        data_version="ds-123",
        model_version="m-456",
        code_version="abc1234",
    )
    fetched = registry.get_run(record.run_id)
    # All three version axes are captured so the run can be reconstructed.
    assert (fetched.data_version, fetched.model_version, fetched.code_version) == (
        "ds-123",
        "m-456",
        "abc1234",
    )


def test_list_runs_filters_by_experiment(registry):
    registry.log_run("a", metrics={"sharpe": 1.0})
    registry.log_run("a", metrics={"sharpe": 1.5})
    registry.log_run("b", metrics={"sharpe": 3.0})
    assert len(registry.list_runs("a")) == 2
    assert len(registry.list_runs()) == 3


def test_best_run_selects_by_metric(registry):
    registry.log_run("x", metrics={"sharpe": 1.0}, notes="low")
    registry.log_run("x", metrics={"sharpe": 2.5}, notes="high")
    registry.log_run("x", metrics={"sharpe": 1.8}, notes="mid")
    best = registry.best_run("sharpe", experiment="x", maximize=True)
    assert best is not None and best.metrics["sharpe"] == 2.5
    worst = registry.best_run("sharpe", experiment="x", maximize=False)
    assert worst is not None and worst.metrics["sharpe"] == 1.0


def test_best_run_none_when_metric_absent(registry):
    registry.log_run("y", metrics={"return": 0.1})
    assert registry.best_run("sharpe", experiment="y") is None


def test_persists_across_instances(tmp_path):
    path = tmp_path / "runs.sqlite3"
    r1 = ExperimentRegistry(path, capture_git=False)
    run = r1.log_run("persist", metrics={"sharpe": 1.1})
    # Reopen from a fresh instance (simulating a restart).
    r2 = ExperimentRegistry(path, capture_git=False)
    assert r2.get_run(run.run_id) is not None
