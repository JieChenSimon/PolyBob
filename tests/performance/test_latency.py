"""Regression checks backed by real PolyBob computation paths."""

import pytest

from tests.performance.hotspot_benchmarks import (
    build_backtest_case,
    build_feature_case,
    build_quant_case,
    run_case,
    warm_numba_kernels,
)


@pytest.mark.performance
@pytest.mark.parametrize(
    ("case", "minimum_throughput"),
    [
        (build_backtest_case(events=2_000), 5_000),
        (build_quant_case(points=2_000), 1_000),
        (build_feature_case(updates=4_000), 10_000),
    ],
)
def test_real_hotspot_throughput(case, minimum_throughput):
    """Catch order-of-magnitude regressions without asserting microbench noise."""
    warm_numba_kernels()
    result = run_case(case, repeats=2, warmups=1)

    assert result.checksum != 0
    assert result.throughput_per_second >= minimum_throughput


def test_benchmark_results_are_structured():
    result = run_case(build_quant_case(points=1_000), repeats=2, warmups=0)

    assert result.module == "libs/quant"
    assert result.operations == 1_000
    assert len(result.durations_ms) == 2
    assert result.min_ms <= result.p95_ms
