from __future__ import annotations

import pytest

from libs.quant.hypothesis import (
    Hypothesis,
    HypothesisRegistry,
    InadmissibleHypothesis,
    Rationale,
    declared_trial_count,
    validate_trial_configuration,
)


def _hypothesis(**kwargs):
    base = dict(
        hypothesis_id="memory-chip-factor",
        claim="Pre-registered fundamental and sector strata predict forward returns.",
        rationale=Rationale.RISK_PREMIUM,
        mechanism="Inventory cycles and capacity constraints can create a delayed risk premium.",
        literature="A factor hypothesis requiring replication after costs.",
        direction="long_after_signal",
        universe="US listed semiconductor issuers",
        horizon_days=252,
        cost_bps=20.0,
        trial_family="memory-chip-factor-v1",
        search_space={
            "fundamental_filter": ("none", "positive_roe"),
            "threshold": (0.0, 0.10),
            "asset_stratum": ("all_semiconductors", "storage_memory"),
        },
        n_configs=8,
    )
    base.update(kwargs)
    return Hypothesis(**base)


def test_filter_threshold_and_strata_cartesian_product_is_counted(tmp_path):
    assert declared_trial_count(_hypothesis().search_space) == 8
    registry = HypothesisRegistry(path=tmp_path / "registry.json")
    registry.register(_hypothesis())
    assert registry.n_trials == 8
    assert registry.entries[0]["hypothesis"]["trial_family"] == "memory-chip-factor-v1"


def test_underdeclared_grid_is_rejected_before_results_exist():
    with pytest.raises(InadmissibleHypothesis, match="understates"):
        _hypothesis(n_configs=1)


def test_winner_must_be_inside_preregistered_grid():
    space = _hypothesis().search_space
    validate_trial_configuration(space, {
        "fundamental_filter": "positive_roe",
        "threshold": 0.10,
        "asset_stratum": "storage_memory",
    })
    with pytest.raises(InadmissibleHypothesis):
        validate_trial_configuration(space, {
            "fundamental_filter": "positive_roe",
            "threshold": 0.20,
            "asset_stratum": "storage_memory",
        })
    with pytest.raises(InadmissibleHypothesis):
        validate_trial_configuration(space, {
            "fundamental_filter": "positive_roe",
            "threshold": 0.10,
            "asset_stratum": "storage_memory",
            "unregistered_sector": "winner",
        })


def test_exploratory_search_also_counts_declared_dimensions(tmp_path):
    registry = HypothesisRegistry(path=tmp_path / "registry.json")
    registry.record_search(
        "memory-chip-screen-v1", 12, "fundamental/threshold/asset sweep",
        trial_family="memory-chip-screen-v1",
        search_space={
            "fundamental_filter": ("none", "positive_roe"),
            "threshold": (0.05, 0.10, 0.15),
            "asset_stratum": ("all", "storage_memory"),
        },
    )
    assert registry.n_trials == 12
    assert tuple(registry.searches[0]["search_space"]["asset_stratum"]) == ("all", "storage_memory")


def test_existing_registry_is_not_mutated_by_the_new_contract():
    registry = HypothesisRegistry()
    assert registry.n_trials > 0
    assert all("hypothesis" in entry or "search" in entry for entry in registry.entries)
