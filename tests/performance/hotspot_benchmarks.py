"""Deterministic benchmarks for PolyBob's real computation paths."""

from __future__ import annotations

import gc
import json
import platform
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Sequence

import numba
import numpy as np
import scipy

from libs.backtest.engine import (
    BacktestConfig,
    BacktestEngine,
    _calculate_max_drawdown_fast,
)
from libs.quant.cointegration import (
    calculate_spread_zscore,
    engle_granger_test,
    kalman_filter_hedge_ratio,
)
from libs.quant.risk_metrics import _calculate_max_drawdown_jit
from libs.schemas import OrderbookTick, Side, TradeTick
from modules.feature_engine.service import MarketFeatures


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    module: str
    unit: str
    operations: int
    workload: Callable[[], float]
    description: str


@dataclass(frozen=True)
class BenchmarkResult:
    name: str
    module: str
    unit: str
    operations: int
    description: str
    repeats: int
    durations_ms: list[float]
    median_ms: float
    p95_ms: float
    min_ms: float
    throughput_per_second: float
    checksum: float


def _percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile requires at least one value")
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * percentile)))
    return ordered[index]


def _time_once(workload: Callable[[], float]) -> tuple[float, float]:
    gc.collect()
    gc.disable()
    try:
        start = time.perf_counter_ns()
        checksum = workload()
        elapsed_ns = time.perf_counter_ns() - start
    finally:
        gc.enable()
    return elapsed_ns / 1_000_000, checksum


def run_case(case: BenchmarkCase, repeats: int = 5, warmups: int = 1) -> BenchmarkResult:
    if repeats < 1:
        raise ValueError("repeats must be positive")
    if warmups < 0:
        raise ValueError("warmups cannot be negative")

    for _ in range(warmups):
        case.workload()

    durations_ms: list[float] = []
    checksums: list[float] = []
    for _ in range(repeats):
        duration_ms, checksum = _time_once(case.workload)
        durations_ms.append(duration_ms)
        checksums.append(checksum)

    if not all(np.isfinite(checksum) for checksum in checksums):
        raise AssertionError(f"{case.name} produced a non-finite checksum")

    median_ms = statistics.median(durations_ms)
    return BenchmarkResult(
        name=case.name,
        module=case.module,
        unit=case.unit,
        operations=case.operations,
        description=case.description,
        repeats=repeats,
        durations_ms=[round(value, 3) for value in durations_ms],
        median_ms=round(median_ms, 3),
        p95_ms=round(_percentile(durations_ms, 0.95), 3),
        min_ms=round(min(durations_ms), 3),
        throughput_per_second=round(case.operations / (median_ms / 1000), 2),
        checksum=round(checksums[-1], 8),
    )


def warm_numba_kernels() -> float:
    """Compile the two Numba drawdown kernels outside steady-state measurements."""
    equity = np.array([100.0, 101.0, 99.0, 102.0], dtype=np.float64)
    start = time.perf_counter_ns()
    _calculate_max_drawdown_fast(equity)
    _calculate_max_drawdown_jit(equity)
    return (time.perf_counter_ns() - start) / 1_000_000


def build_backtest_case(events: int = 20_000, markets: int = 16) -> BenchmarkCase:
    if events < 2 or markets < 1:
        raise ValueError("events must be >= 2 and markets must be positive")

    indices = np.arange(events, dtype=np.float64)
    prices = 0.50 + np.sin(indices / 37.0) * 0.04 + np.cos(indices / 113.0) * 0.01
    timestamps = [
        datetime(2025, 1, 2, 14, 30) + timedelta(milliseconds=index * 250)
        for index in range(events)
    ]
    market_ids = [f"market-{index}" for index in range(markets)]

    def workload() -> float:
        engine = BacktestEngine(
            BacktestConfig(
                initial_capital=10_000_000.0,
                fee_rate=0.002,
                slippage_bps=10.0,
                market_depth=100_000.0,
                # This synthetic throughput fixture intentionally alternates
                # long/short events on fresh instruments. Production/default
                # backtests remain spot-only unless this contract is explicit.
                allow_short=True,
            )
        )
        market_prices = {market_id: 0.5 for market_id in market_ids}

        for index in range(events):
            market_id = market_ids[index % markets]
            price = float(prices[index])
            side = Side.BUY_YES if index % 2 == 0 else Side.SELL_YES
            engine.execute_signal(
                timestamps[index],
                market_id,
                side,
                price,
                size=10.0 + (index % 5),
                volatility=0.01 + (index % 7) * 0.001,
            )
            market_prices[market_id] = price
            engine.update_equity(timestamps[index], market_prices)

        results = engine.get_results()
        if results["num_trades"] != events:
            raise AssertionError("backtest workload did not execute every event")
        return (
            results["final_equity"]
            + results["max_drawdown"]
            + results["total_fees"]
            + results["num_trades"]
        )

    return BenchmarkCase(
        name="backtest_event_loop",
        module="libs/backtest",
        unit="events",
        operations=events,
        workload=workload,
        description="execute_signal + update_equity + get_results over a multi-market event stream",
    )


def build_quant_case(points: int = 20_000, lookback: int = 60) -> BenchmarkCase:
    if points <= lookback:
        raise ValueError("points must exceed lookback")

    rng = np.random.default_rng(20260613)
    x = 100.0 + np.cumsum(rng.normal(0.0, 0.35, points))
    residual = np.empty(points, dtype=np.float64)
    residual[0] = 0.0
    innovations = rng.normal(0.0, 0.2, points)
    for index in range(1, points):
        residual[index] = 0.92 * residual[index - 1] + innovations[index]
    y = 1.35 * x + 2.0 + residual

    def workload() -> float:
        result = engle_granger_test(y, x)
        betas, covariance = kalman_filter_hedge_ratio(y, x)
        zscores = calculate_spread_zscore(y, x, result.hedge_ratio, lookback=lookback)
        return (
            result.hedge_ratio
            + result.adf_statistic
            + float(betas[-1])
            + float(covariance[-1])
            + float(np.sum(zscores[-lookback:]))
        )

    return BenchmarkCase(
        name="quant_pair_pipeline",
        module="libs/quant",
        unit="points",
        operations=points,
        workload=workload,
        description="Engle-Granger + Kalman hedge ratio + rolling spread Z-score",
    )


def build_feature_case(updates: int = 40_000, trade_every: int = 4) -> BenchmarkCase:
    if updates < 2 or trade_every < 1:
        raise ValueError("updates must be >= 2 and trade_every must be positive")

    start = datetime.utcnow() - timedelta(milliseconds=updates * 10)
    orderbooks: list[OrderbookTick] = []
    trades: list[TradeTick | None] = []
    trade_count = 0

    for index in range(updates):
        mid = 0.5 + np.sin(index / 53.0) * 0.03
        spread = 0.001 + (index % 7) * 0.00005
        timestamp = start + timedelta(milliseconds=index * 10)
        orderbooks.append(
            OrderbookTick(
                market_id="feature-benchmark",
                timestamp=timestamp,
                bid_price=float(mid - spread / 2),
                ask_price=float(mid + spread / 2),
                bid_size=1000.0 + index % 300,
                ask_size=900.0 + index % 250,
            )
        )
        if index % trade_every == 0:
            trades.append(
                TradeTick(
                    market_id="feature-benchmark",
                    timestamp=timestamp,
                    price=float(mid),
                    size=5.0 + index % 11,
                    side="buy" if index % 2 == 0 else "sell",
                )
            )
            trade_count += 1
        else:
            trades.append(None)

    operations = updates + trade_count

    def workload() -> float:
        features = MarketFeatures("feature-benchmark")
        for orderbook, trade in zip(orderbooks, trades):
            features.update_from_orderbook(orderbook)
            if trade is not None:
                features.update_from_trade(trade)
        snapshot = features.to_dict()
        return (
            snapshot["mid_price"]
            + snapshot["spread_bps"]
            + snapshot["depth_imbalance"]
            + snapshot["trade_intensity_1m"]
            + snapshot["volume_1m"]
            + snapshot["price_jump_score"]
        )

    return BenchmarkCase(
        name="feature_stream_updates",
        module="modules/feature_engine",
        unit="updates",
        operations=operations,
        workload=workload,
        description="orderbook and trade updates through MarketFeatures, including rolling statistics",
    )


def build_suite(scale: str = "standard") -> list[BenchmarkCase]:
    if scale == "quick":
        return [
            build_backtest_case(events=5_000),
            build_quant_case(points=5_000),
            build_feature_case(updates=10_000),
        ]
    if scale == "standard":
        return [
            build_backtest_case(),
            build_quant_case(),
            build_feature_case(),
        ]
    raise ValueError(f"unknown benchmark scale: {scale}")


def environment_metadata() -> dict[str, str]:
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version.replace("\n", " "),
        "numpy": np.__version__,
        "numba": numba.__version__,
        "scipy": scipy.__version__,
    }


def run_suite(scale: str = "standard", repeats: int = 5, warmups: int = 1) -> dict:
    numba_warmup_ms = warm_numba_kernels()
    results = [run_case(case, repeats=repeats, warmups=warmups) for case in build_suite(scale)]
    return {
        "metadata": environment_metadata(),
        "configuration": {
            "scale": scale,
            "repeats": repeats,
            "warmups": warmups,
            "numba_warmup_ms": round(numba_warmup_ms, 3),
        },
        "results": [asdict(result) for result in results],
    }


def write_json(report: dict, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
