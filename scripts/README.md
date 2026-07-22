# scripts/

One-off research and operations scripts. **The canonical backtest path is
`libs/backtest` (engine, metrics, analyzer, walk-forward) with
`libs/backtest/cli.py` as the entrypoint helper — new backtests should build
on that, not copy code from these scripts.**

Clearly-superseded duplicates have been moved to `scripts/archive/`. They are
kept runnable (nothing in the codebase imports from `scripts/`), but should
not be used as a starting point for new work.

## Current scripts

| Script | Purpose | Entrypoint | Status |
| --- | --- | --- | --- |
| `run_backtest.py` | Thin runner over the canonical `libs/backtest/cli.py` (`run_backtest`/`print_results`) | `python scripts/run_backtest.py <data_file>` | current |
| `backtest_fusion.py` | Signal-fusion strategy backtest on real Binance data via `libs.backtest` engine + analyzer | `python scripts/backtest_fusion.py` | current |
| `backtest_enhanced.py` | Enhanced (cointegration/mean-reversion) strategy backtest on real Binance data | `python scripts/backtest_enhanced.py` | current |
| `backtest_contract.py` | Contract strategy backtest validation via `libs.backtest` | `python scripts/backtest_contract.py` | current |
| `quick_validation.py` | Smoke-tests the `libs.backtest` engine on generated mock data | `python scripts/quick_validation.py` | current |
| `optimize_params.py` | Parameter sweep for the cointegration strategy (synthetic data) | `python scripts/optimize_params.py` | current |
| `btc_decision_enhanced.py` | Live BTC decision: math model + AI analysis | `python scripts/btc_decision_enhanced.py` | current |
| `btc_dual_ma.py` | Live BTC decision using `strategies.dual_ma_strategy` | `python scripts/btc_dual_ma.py` | current |
| `predict_btc.py` | BTC prediction: realtime data + indicators + AI + signal fusion | `python scripts/predict_btc.py` | current |
| `auto_decide.py` | Decide next step from a collected-data analysis JSON | `python scripts/auto_decide.py <data_file>` | current |
| `ai_strategy_demo.py` | Minimal AI event-driven strategy demo | `python scripts/ai_strategy_demo.py` | current |
| `demo_contract_strategy.py` | Contract trading strategy demo (math model + AI fusion) | `python scripts/demo_contract_strategy.py` | current |
| `full_system_demo.py` | End-to-end system demo (strategy + execution + risk) | `python scripts/full_system_demo.py` | current |
| `collect_realtime_data.py` | Collect Polymarket realtime data via CLOB API | `python scripts/collect_realtime_data.py` | current |
| `analyze_realtime_data.py` | Backtest/analyze collected realtime snapshots | `python scripts/analyze_realtime_data.py` | current |
| `fetch_historical_data.py` | Fetch Polymarket historical data for backtests | `python scripts/fetch_historical_data.py` | current |
| `quick_snapshot.py` | Quick market snapshot | `python scripts/quick_snapshot.py` | current |
| `check_api.py` | Inspect Polymarket API response shapes | `python scripts/check_api.py` | current |
| `test_crypto_exchanges.py` | Cross-market demo (Polymarket + crypto exchanges) | `python scripts/test_crypto_exchanges.py` | current |
| `test_integration.py` | Manual integration check: AI strategy + execution + risk | `python scripts/test_integration.py` | current |
| `run_tests.py` | Convenience wrapper to run the test suite | `python scripts/run_tests.py` | current |
| `run_performance_benchmarks.py` | Deterministic hotspot benchmark suite | `python scripts/run_performance_benchmarks.py` | current |

## Archived scripts (`scripts/archive/`)

Superseded duplicates; still runnable, kept for reference only.

| Script | Purpose | Superseded by | Status |
| --- | --- | --- | --- |
| `archive/backtest_fusion_simple.py` | Self-contained toy fusion backtest on synthetic data | `backtest_fusion.py` (real data, `libs.backtest`) | archived |
| `archive/enhanced_backtest.py` | Enhanced strategy backtest on synthetic cointegrated data | `backtest_enhanced.py` (real data); synthetic sweep lives in `optimize_params.py` | archived |
| `archive/full_backtest.py` | Slim metric-only variant of the enhanced backtest | `backtest_enhanced.py` + `libs/backtest/metrics.py` | archived |
| `archive/validate_strategy.py` | Hand-rolled backtest loop for strategy validation | `run_backtest.py` + `libs/backtest` | archived |
| `archive/btc_decision.py` | Basic BTC decision (indicators only) | `btc_decision_enhanced.py` | archived |
| `archive/predict_btc_with_claude.py` | BTC prediction with a hardcoded one-off AI analysis | `predict_btc.py` | archived |
