from __future__ import annotations

import pytest

from scripts.btc5m_statistical_audit import audit, _drawdown, _partition


def _rows(days: int = 30, per_day: int = 2, value: float = 0.1):
    return [
        {"date": f"2026-01-{day:02d}", "excess": value, "entry_price": "0.5"}
        for day in range(1, days + 1) for _ in range(per_day)
    ]


def test_temporal_split_uses_disjoint_chronological_labels():
    parts = _partition([f"2026-01-{day:02d}" for day in range(1, 11)])
    assert parts["train"][-1] < parts["validation"][0] < parts["test"][0]
    assert not set(parts["train"]) & set(parts["validation"]) & set(parts["test"])


def test_month_split_is_unknown_with_one_month_even_when_returns_are_positive():
    report = audit({"collection_status": "complete", "real_data_only": True,
                    "result": {"events": _rows(days=30, per_day=1)}}, n_trials=255)
    assert report["month_split"]["status"] == "UNKNOWN"
    assert report["promotion_status"] == "UNKNOWN"
    assert report["overall"]["mean_pct"] > 0


def test_cluster_floor_blocks_positive_small_sample_and_wild_p_cannot_override():
    report = audit({"collection_status": "complete", "real_data_only": True,
                    "result": {"events": _rows(days=10, per_day=10)}}, n_trials=255)
    assert report["overall"]["n"] == 100
    assert report["overall"]["n_clusters"] == 10
    assert report["overall"]["status"] == "UNKNOWN"
    assert report["gates"]["cluster_inference"] == "UNKNOWN"
    assert report["promotion_status"] == "UNKNOWN"


def test_multiple_testing_hurdle_is_recorded_and_drawdown_known_answer():
    report = audit({"collection_status": "complete", "real_data_only": True,
                    "result": {"events": _rows(days=30, per_day=1)}}, n_trials=255)
    assert report["multiple_testing"]["t_hurdle"] == pytest.approx(4.2033, abs=1e-4)
    dd = _drawdown([
        {"date": "2026-01-01", "excess": 0.1, "entry_price": "0.5"},
        {"date": "2026-01-02", "excess": -0.2, "entry_price": "0.5"},
        {"date": "2026-01-03", "excess": 0.1, "entry_price": "0.5"},
    ])
    assert dd["max_drawdown"] == pytest.approx(0.2 / 1.1, abs=1e-6)
    assert dd["threshold_status"] == "NOT_SPECIFIED"


def test_current_snapshot_keeps_positive_oos_unknown():
    import json
    from pathlib import Path

    payload = json.loads(Path("data/btc5m_mispricing.json").read_text())
    report = audit(payload)
    assert report["overall"]["mean_pct"] > 0
    assert report["date_split"]["status"] == "UNKNOWN"
    assert report["month_split"]["status"] == "UNKNOWN"
    assert report["promotion_status"] == "UNKNOWN"
