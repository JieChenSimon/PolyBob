# PB-0040 US cross-sectional multifold kernel replay

Date: 2026-08-25

## Contract

- Real local US daily bars, 26 symbols from `US_LIQUID`
- Input snapshot SHA-256:
  `5bc5c9ab66fc19e06fb199133041e78bd7b1780104e7f6bfed8df23c7548623b`
- Signal fixed before replay: lookback 60, top 30%, rebalance 10 sessions,
  long-only
- Real `modules.simulation.SimulationService` fills, fees and ledger
- Fee: 20 bps; midpoint penalty: 10 bps
- Four chronological cut dates; no OOS parameter selection
- Equity sampled every five bars while every fill remained in the ledger
- CPU throttle target: at most 45% average process share; observed process use
  was approximately 22–26%

## Fold results

| OOS cut | Mean return | Median return | Positive instruments | Mean excess vs buy/hold | Positive excess |
|---|---:|---:|---:|---:|---:|
| 2024-02-09 | 2.07% | 0.61% | 14/26 | -67.82% | 2/26 |
| 2024-08-13 | 1.99% | 1.07% | 15/26 | -67.96% | 2/26 |
| 2025-02-14 | 1.39% | -0.15% | 13/26 | -48.75% | 4/26 |
| 2025-08-19 | 1.11% | -0.43% | 10/26 | -34.04% | 6/26 |

Only 6 of 26 instruments were positive in all four folds: AAPL, AMD, GOOGL,
INTC, MRK and XOM. This is descriptive persistence, not a promotion result:
the fold sample is short, the per-instrument monthly/annual target gate was not
computed by this runner, and historical executable depth is unresolved.

## Interpretation

Absolute returns remained positive in the arithmetic mean, but the strategy
underperformed the corresponding buy-and-hold comparison in every fold. The
median and positive-instrument coverage deteriorated in the later folds, which
is inconsistent with a stable cross-sectional alpha. The six all-positive
symbols require a separate frozen-universe confirmation and must not be
selected from these OOS results for live use.

The run is therefore `replay_only_not_promoted`. It does not satisfy the user's
50% annual and 15% complete-month requirements and does not establish an
executable trading edge.

## Next action

Use the immutable input snapshot to run a separate per-instrument capital
replay for the six descriptive symbols with monthly/annual gates and a new
out-of-time extension. Do not alter the 60/30/10 signal based on these fold
results; the universe and signal must remain frozen until that confirmation.
