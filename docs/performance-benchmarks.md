# PolyBob Performance Benchmarks

## Purpose

This suite measures real PolyBob computation paths before any Rust migration.
It replaces the previous latency tests, which measured `asyncio.sleep` rather
than application code.

The benchmark is deterministic and performs no network I/O. Input series are
generated once, outside the timed section, then passed through production
classes and functions. This isolates computation cost while keeping the exact
runtime path reproducible.

## Covered Paths

| Benchmark | Production path | Standard workload |
| --- | --- | ---: |
| `backtest_event_loop` | `BacktestEngine.execute_signal`, `update_equity`, `get_results` | 20,000 events across 16 markets |
| `quant_pair_pipeline` | Engle-Granger, Kalman hedge ratio, rolling spread Z-score | 20,000 paired observations |
| `feature_stream_updates` | `MarketFeatures.update_from_orderbook`, `update_from_trade`, `to_dict` | 40,000 books + 10,000 trades |

Data generation, Pydantic input construction, garbage collection, and Numba
compilation are outside steady-state timings. Each timed run creates fresh
application state and validates a numeric checksum so the work cannot be
optimized away.

## Baseline

Measured on June 13, 2026:

- macOS 26.5.1, arm64
- Python 3.11.15
- NumPy 2.4.4
- Numba 0.65.0
- SciPy 1.17.1
- 2 warmups, 7 measured repetitions

| Benchmark | Median | P95 | Median throughput |
| --- | ---: | ---: | ---: |
| Backtest event loop | 69.588 ms | 71.299 ms | 287,407 events/s |
| Quant pair pipeline | 114.662 ms | 191.948 ms | 174,426 points/s |
| Feature stream updates | 162.251 ms | 170.269 ms | 308,165 updates/s |

The Numba drawdown kernels required 280.925 ms to initialize in the benchmark
process. That cost is reported separately and excluded from steady-state
throughput. The machine-readable result is stored in
`tests/performance/results/baseline-macos-arm64.json`.

These values are a local baseline, not universal latency targets. Compare
changes on the same machine, environment, scale, and power mode. The pytest
thresholds are intentionally loose and only reject order-of-magnitude
regressions.

## First Optimization Result

After replacing the feature engine's repeated trade-deque scans with maintained
rolling count/volume state, and fixing fixed-window price eviction, the same
standard benchmark reported:

| Benchmark | Before median | After median | Change |
| --- | ---: | ---: | ---: |
| Feature stream updates | 162.251 ms | 45.033 ms | 3.60x faster |

Feature throughput increased from 308,165 to 1,110,289 updates/s. This confirms
the migration rule: improve the algorithm and data structure before adding a
Rust boundary. Backtest and quant results from that run are not treated as new
baselines because system load produced higher run-to-run variance.

## Rust Core v1

The first Rust extension crate now lives in `rust/polybob-core` and exposes
CPU-heavy kernels through PyO3:

| Kernel | Python facade | Purpose |
| --- | --- | --- |
| `rolling_zscore` | `libs.compute.rolling_zscore` | Rolling spread Z-score without per-window Python loops |
| `kalman_hedge_ratio` | `libs.compute.kalman_hedge_ratio` | Dynamic hedge-ratio loop with the GIL released |
| `risk_metrics` | `libs.compute.risk_metrics` | VaR, CVaR, drawdown, Sharpe, Sortino and Calmar |
| `max_drawdown` | `libs.compute.max_drawdown` | Single-pass drawdown with peak/trough indexes |
| `slippage_batch` | `libs.compute.slippage_batch` | Batch backtest slippage formula |

`POLYBOB_COMPUTE_BACKEND=python` remains the default. Use `rust` after the
extension is installed, or `verify` to compare Rust and Python outputs. The
fallback flag is `POLYBOB_RUST_FALLBACK_ENABLED=true`.

Validation added in this phase:

- Rust crate unit tests for quant, risk and backtest kernels.
- Clippy with warnings denied for the Rust crate.
- Python facade tests that prove default Python parity, Rust fallback behavior,
  and optional Rust/Python parity when the extension is installed.
- A lightweight performance regression test for the vectorized slippage facade.

## Profile Findings

Function-level profiling explains the totals:

1. `calculate_spread_zscore` consumed about 94% of the quant pipeline profile.
   It executes a Python loop and recomputes NumPy mean and standard deviation
   for every overlapping window.
2. In the backtest profile, `update_equity` and its position dictionary scan
   were the largest cost, followed by per-event `execute_signal` object work.
3. Feature updates already have high throughput. The notable remaining Python
   cost is `update_from_trade`, which scans the bounded recent-trade deque twice
   per trade. Pydantic validation is an ingestion cost and is intentionally
   excluded from steady-state update timing.

## Rust Migration Order

### 1. Quant rolling kernels

Highest priority, but first try a vectorized or Numba implementation in Python.
The current rolling Z-score algorithm repeats window reductions and is the
clearest CPU hotspot. If production workloads require many pairs or long
histories after that optimization, move rolling statistics and the Kalman loop
into a contiguous Rust kernel exposed through PyO3.

Acceptance gate:

- Identical results within an explicitly chosen floating-point tolerance.
- At least 3x median speedup on the standard quant workload.
- No slower end-to-end performance after Python/Rust boundary overhead.

### 2. Backtest state transition kernel

Second priority for large portfolio simulations. A Rust implementation can
store positions, trades, and equity in contiguous structures and avoid repeated
Python dictionary scans and dataclass allocation. Migrate the event-state
transition as one coarse call; moving only the drawdown calculation is not
worthwhile because it is already Numba compiled.

Acceptance gate:

- Event-for-event parity for fills, fees, capital, positions, and drawdown.
- At least 2x median speedup at 100,000+ events.
- Deterministic replay and unchanged failure behavior.

### 3. Feature engine rolling state

Defer Rust. The measured update path exceeds 300,000 updates/s on this machine,
and the service is more likely to be constrained by event transport and
serialization. First replace repeated deque scans with maintained rolling
volume/count state and benchmark the complete event-bus path. Consider Rust
only if measured production ingestion exceeds the optimized Python budget.

## Commands

Run the standard benchmark and save JSON:

```bash
conda run -n polybob python scripts/run_performance_benchmarks.py \
  --scale standard --repeats 7 --warmups 2 \
  --json-output tests/performance/results/baseline-macos-arm64.json
```

Run the fast regression tests:

```bash
conda run -n polybob python -m pytest -q tests/performance/test_latency.py
```

Run the full Python suite:

```bash
conda run -n polybob python -m pytest -q
```
