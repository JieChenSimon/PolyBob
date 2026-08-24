from __future__ import annotations

import json
from pathlib import Path

from libs.quant.statistical_manifest import build_statistical_manifest, validate_statistical_manifest


def _load(name: str):
    return json.loads(Path("data", name).read_text())


def test_three_reports_share_one_fail_closed_statistical_contract():
    manifest = build_statistical_manifest(
        _load("btc5m_calibration.json"),
        _load("btc5m_direction_kernel_replay.json"),
        _load("btc5m_mispricing.json"),
        event_n_trials=255,
    )
    assert validate_statistical_manifest(manifest) == []
    assert manifest["promotion_status"] == "UNKNOWN"
    assert manifest["rules"]["positive_mean_does_not_pass"] is True
    assert manifest["rules"]["positive_oos_does_not_pass"] is True


def test_calibration_missing_oos_and_multiple_testing_is_unknown():
    manifest = build_statistical_manifest(
        _load("btc5m_calibration.json"),
        _load("btc5m_direction_kernel_replay.json"),
        _load("btc5m_mispricing.json"),
        event_n_trials=255,
    )
    calibration = manifest["studies"]["calibration"]
    assert calibration["status"] == "UNKNOWN"
    assert calibration["temporal_split"]["available"] is False
    assert calibration["oos"]["available"] is False
    assert calibration["multiple_testing"]["status"] == "UNKNOWN"
    assert calibration["cluster_floor"]["status"] == "UNKNOWN"


def test_direction_is_not_polymarket_evidence_and_does_not_pass_cluster_gate():
    manifest = build_statistical_manifest(
        _load("btc5m_calibration.json"),
        _load("btc5m_direction_kernel_replay.json"),
        _load("btc5m_mispricing.json"),
        event_n_trials=255,
    )
    direction = manifest["studies"]["direction"]
    assert "spot proxy" in manifest["scope"]
    assert direction["temporal_split"]["available"] is True
    assert direction["oos"]["available"] is True
    assert direction["cluster_floor"]["status"] == "UNKNOWN"
    assert direction["multiple_testing"]["status"] == "FAIL"


def test_event_positive_oos_and_wild_p_do_not_override_cluster_floor_or_target():
    manifest = build_statistical_manifest(
        _load("btc5m_calibration.json"),
        _load("btc5m_direction_kernel_replay.json"),
        _load("btc5m_mispricing.json"),
        event_n_trials=255,
    )
    event = manifest["studies"]["event"]
    assert event["oos"]["mean_pnl_per_contract"] > 0
    assert event["status"] == "UNKNOWN"
    assert event["temporal_split"]["available"] is True
    assert event["oos"]["status"] == "UNKNOWN"
    assert event["cluster_floor"]["status"] == "UNKNOWN"
    assert event["return_target"]["status"] == "UNKNOWN"
    assert event["drawdown"]["threshold_status"] == "NOT_SPECIFIED"
    assert event["drawdown"]["negative_events"] > 0
    assert event["drawdown"]["max_observed"] > event["drawdown"]["source_period_max"]
    assert event["multiple_testing"]["analysis_status"] == "APPLIED"
    assert event["multiple_testing"]["status"] == "UNKNOWN"
    assert manifest["unified_gates"]["multiple_testing"] == "FAIL"


def test_validator_rejects_false_pass_for_insufficient_clusters_and_months():
    manifest = {
        "schema_version": "btc5m-statistical-manifest-v1",
        "promotion_status": "UNKNOWN",
        "rules": {"positive_mean_does_not_pass": True, "positive_oos_does_not_pass": True,
                  "min_independent_clusters": 20, "min_complete_return_target_months": 12},
        "studies": {"fake": {"cluster_floor": {"observed": 3, "status": "PASS"},
                               "return_target": {"complete_months": 1, "status": "PASS"}}},
    }
    errors = validate_statistical_manifest(manifest)
    assert "fake:cluster_floor_passed_below_minimum" in errors
    assert "fake:return_target_passed_with_insufficient_months" in errors
