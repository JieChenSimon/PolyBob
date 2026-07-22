"""P5: honest native-core status + a real Rust-vs-Python benchmark."""

from __future__ import annotations

import importlib.util

import numpy as np
import pytest

from libs.compute import (
    benchmark_rolling_zscore,
    native_core_available,
    native_core_status,
    rolling_zscore,
)
from libs.compute import backend as compute_backend

_NATIVE_BUILT = importlib.util.find_spec("polybob_core") is not None


def test_status_reports_real_state(monkeypatch):
    monkeypatch.delenv("POLYBOB_COMPUTE_BACKEND", raising=False)
    status = native_core_status()

    assert status["native_core_built"] == _NATIVE_BUILT
    assert status["native_core_built"] == native_core_available()
    # The shim must not pretend the native path is active when it is not.
    assert status["status"] == (
        "native core built" if _NATIVE_BUILT else "native core not built"
    )
    assert status["configured_backend"] == "python"
    assert status["resolved_backend"] == "python"
    assert status["auto_would_use"] == ("rust" if _NATIVE_BUILT else "python")


def test_auto_backend_resolves_by_availability(monkeypatch):
    monkeypatch.setenv("POLYBOB_COMPUTE_BACKEND", "auto")
    assert compute_backend._selected_backend() == ("rust" if _NATIVE_BUILT else "python")


def test_auto_backend_matches_python_numerically():
    x = np.linspace(100.0, 130.0, 512, dtype=np.float64)
    y = 1.2 * x + np.sin(np.arange(512, dtype=np.float64) / 5.0)
    np.testing.assert_allclose(
        rolling_zscore(y, x, 1.2, lookback=30, backend="auto"),
        rolling_zscore(y, x, 1.2, lookback=30, backend="python"),
    )


def test_benchmark_runs_python_path_without_native():
    report = benchmark_rolling_zscore(points=5_000, lookback=30, repeats=2)
    assert report["python_ms"] > 0
    assert "python" in report["backends"]
    assert report["native_core_built"] == _NATIVE_BUILT
    if not _NATIVE_BUILT:
        assert report["rust_ms"] is None
        assert report["speedup"] is None


@pytest.mark.skipif(not _NATIVE_BUILT, reason="polybob_core native extension not built")
def test_benchmark_compares_rust_vs_python_when_built(capsys):
    report = benchmark_rolling_zscore(points=50_000, lookback=60, repeats=3)

    assert report["backends"] == ["python", "rust"]
    assert report["rust_ms"] is not None and report["rust_ms"] > 0
    assert report["results_match"] is True
    assert report["speedup"] is not None
    # Surface the real numbers so the benchmark is visible under -s.
    print(
        f"rolling_zscore benchmark: python={report['python_ms']}ms "
        f"rust={report['rust_ms']}ms speedup={report['speedup']}x"
    )
