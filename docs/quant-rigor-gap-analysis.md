# Quant Rigor Gap Analysis & Remediation

Companion to [`productionization-roadmap.md`](productionization-roadmap.md). It
records the gap between PolyBob and professional quant tooling, what was fixed
in the `libs/quant/*` + `libs/research/*` rigor layer, how each fix is tested,
and what still needs infrastructure.

The guiding principle from the literature: a backtest is a **filter that
discards bad strategies**, not a predictor of success. ~95% of backtested
strategies fail live, and a search over enough configurations will produce a
Sharpe > 2 by luck alone. Rigor means quantifying and controlling bias, not
chasing equity curves.

## Status by problem

| # | Problem | Status | Where | Tests |
| - | ------- | ------ | ----- | ----- |
| 1 | Look-ahead / point-in-time protection | **Solved + applied** | `libs/quant/pit.py` | `test_pit_lookahead.py`, `test_strategy_causality.py` |
| 2 | Research ≠ production code path | **Partial (pattern proven)** | `test_strategy_causality.py` (research==live for DualMA) | same |
| 3 | Survivorship-free universe | **Solved (mechanism)** | `libs/quant/universe.py` | `test_universe.py` |
| 4 | Time-series data store | **Deferred (needs infra)** | — | — |
| 5 | Data-quality / freshness gate | **Solved** | `libs/quant/data_quality.py` | `test_data_quality.py` |
| 6 | Strategy promotion gate (DSR/PSR) | **Solved + reachable** | `libs/quant/promotion.py`, `/api/simulation/runs/{id}/promotion` | `test_promotion_gate.py`, `test_simulation_api.py` |
| 7 | Cost-stress realism | **Solved (lib)** | `libs/quant/promotion.py::cost_stress_test` | `test_promotion_gate.py` |
| 8 | Experiment tracking / reproducibility | **Solved (lib)** | `libs/research/registry.py` | `test_experiment_registry.py` |
| 9 | Concept-drift / circuit breakers | **Partial (detector done)** | `libs/quant/drift.py` | `test_drift.py` |

## What each module gives you

- **`pit.py`** — `PointInTimeSeries` (values tagged with `available_at` so future
  publications can't leak), `lag_signals` (decide on the last closed bar), and
  `assert_no_lookahead` / `find_lookahead` — a harness that *proves* a signal is
  causal by checking bar `k`'s signal doesn't change when future bars appear.
  Applied to `DualMAStrategy` and `calculate_spread_zscore` as regression
  guards; both verified causal.
- **`promotion.py`** — statistically correct Probabilistic and Deflated Sharpe
  Ratios (Bailey & López de Prado; skew/kurtosis-aware, trial-count-aware),
  `min_track_record_length`, `cost_stress_test` (edge must survive rising costs
  *and* Sharpe must degrade — cost-insensitivity is a red flag), and a
  `PromotionGate` combining sample-size + DSR + cost-stress + walk-forward
  stability into a PASS/FAIL with per-check reasons. Reachable at
  `GET /api/simulation/runs/{run_id}/promotion`.
- **`data_quality.py`** — freshness / completeness / schema checks that combine
  into an `ok` / `degraded` / `blocked` verdict, so stale or malformed data
  explicitly blocks or downgrades a conclusion (roadmap "Failure behavior" gate).
- **`universe.py`** — `PointInTimeUniverse.active_as_of(t)` returns the
  survivor-free tradable set including resolved/delisted markets.
- **`drift.py`** — PSI + two-sample KS drift detection to flag regime change /
  model decay (the trigger for re-validation).
- **`research/registry.py`** — sqlite-backed, server-free run registry logging
  params, metrics, and data/model/code versions so any result is reproducible
  ("Traceable output" gate).

## Remaining work (needs infrastructure or larger refactor)

1. **Unify every strategy's signal path (problem 2).** Only `DualMAStrategy` is
   proven research==live. Route all strategies through one causal signal
   library imported by both backtest and live, and retire the duplicate API
   runtime (`apps/api/main.py` vs `modules/api_server/main.py`).
2. **Populate the PIT universe from real history (problem 3).** Persist each
   Polymarket market's listing/resolution time and each token's listing/delist
   time from `market_discovery`, then back the universe with it.
3. **Time-series store (problem 4).** Move history off sqlite to Timescale (URL
   already configured) or a DuckDB/Parquet lakehouse for reproducible research
   at scale and a feature store to prevent training-serving skew.
4. **Wire the gates into pipelines.** Call `data_quality.validate_record` in the
   feature/news ingestion paths; log every backtest/sim run to the registry;
   feed cost-parameterised returns from the backtest into the promotion
   endpoint (it currently evaluates DSR + sample size only).
5. **Drift → action (problem 9).** Connect `detect_drift` to an auto-revalidate
   trigger and model circuit breakers that halt trading on performance decay.

## References

- StarQube — critical pitfalls of backtesting
- Susan Potter — a taxonomy of backtest lies (survivorship, look-ahead, …)
- Bailey & López de Prado — Deflated Sharpe Ratio, Probabilistic Sharpe Ratio
- Brenndoerfer — quant trading system architecture & backtesting frameworks
