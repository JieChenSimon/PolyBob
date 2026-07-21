"""Tests for concept-drift detection (PSI + KS)."""

from __future__ import annotations

import numpy as np

from libs.quant.drift import (
    DriftLevel,
    detect_drift,
    population_stability_index,
    psi_level,
)


def _normal(mean, std, n, seed):
    return np.random.default_rng(seed).normal(mean, std, n)


def test_psi_near_zero_for_same_distribution():
    ref = _normal(0, 1, 5000, 1)
    cur = _normal(0, 1, 5000, 2)
    psi = population_stability_index(ref, cur)
    assert psi < 0.10
    assert psi_level(psi) is DriftLevel.NONE


def test_psi_large_for_shifted_distribution():
    ref = _normal(0, 1, 5000, 1)
    cur = _normal(2.0, 1, 5000, 2)  # big mean shift
    psi = population_stability_index(ref, cur)
    assert psi > 0.25
    assert psi_level(psi) is DriftLevel.SIGNIFICANT


def test_detect_drift_flags_regime_change():
    ref = _normal(0, 1, 3000, 1)
    cur = _normal(1.5, 2.0, 3000, 2)
    report = detect_drift(ref, cur)
    assert report.drifted
    assert report.level is not DriftLevel.NONE
    assert report.ks_pvalue < 0.05


def test_detect_drift_quiet_when_stable():
    ref = _normal(0, 1, 3000, 1)
    cur = _normal(0, 1, 3000, 2)
    report = detect_drift(ref, cur)
    assert not report.drifted
    assert report.level is DriftLevel.NONE


def test_psi_handles_empty_input():
    assert population_stability_index([], [1.0, 2.0]) == 0.0
    assert population_stability_index([1.0, 2.0], []) == 0.0


def test_psi_handles_degenerate_baseline():
    # All-equal baseline should not crash.
    psi = population_stability_index([1.0] * 100, [1.0, 2.0, 3.0])
    assert psi >= 0.0


def test_report_serializes():
    report = detect_drift(_normal(0, 1, 500, 1), _normal(0, 1, 500, 2))
    d = report.to_dict()
    assert set(d) == {"level", "psi", "ks_statistic", "ks_pvalue", "drifted", "detail"}
