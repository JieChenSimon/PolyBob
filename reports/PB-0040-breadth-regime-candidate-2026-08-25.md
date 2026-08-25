# PB-0040 causal breadth-regime candidate — 2026-08-25

## Decision

**Reject the candidate.** A causal market-breadth gate was pre-registered and replayed against
the same 26-symbol signal universe, six frozen evaluation symbols, 56 complete months, costs,
and `SimulationService` execution path. It reduced or redistributed exposure but did not improve
the required return gates or the portfolio-wide evidence.

## Candidate contract

- Baseline signal unchanged: lookback 60, top 30%, rebalance 10 sessions, `vol_target_10`
- New rule: only retain the existing target when at least 50% of the full 26-symbol signal
  universe has a positive causal 60-observation return at that date
- No use of future returns, evaluation-symbol outcomes, or post-hoc symbol selection
- Window: 2022-01-03 through 2026-08-24
- Same isolated $100,000 accounts, fees, mid-price penalty, and depth status as baseline
- Snapshot: `5bc5c9ab66fc19e06fb199133041e78bd7b1780104e7f6bfed8df23c7548623b`
- Artifact: `data/cross_sectional_six_breadth05_2022.json`

## Baseline versus candidate

| Symbol | Baseline ann. | Candidate ann. | Baseline DD | Candidate DD | Baseline trades | Candidate trades | Candidate months ≥15% |
|---|---:|---:|---:|---:|---:|---:|---:|
| AAPL | 1.07% | 5.38% | 33.67% | 14.78% | 8 | 14 | 0/56 |
| AMD | 37.26% | 11.05% | 35.79% | 34.64% | 8 | 18 | 5/56 |
| GOOGL | -0.20% | 2.57% | 26.56% | 24.32% | 9 | 11 | 1/56 |
| INTC | 14.38% | 5.09% | 48.18% | 35.03% | 13 | 15 | 4/56 |
| MRK | 10.09% | 4.60% | 16.31% | 15.30% | 8 | 10 | 1/56 |
| XOM | 6.33% | 2.47% | 33.54% | 19.13% | 9 | 15 | 1/56 |

## Attribution

- The filter lowered drawdown for AAPL, INTC, and XOM, but it also increased turnover and
  explicit costs for every symbol.
- AMD, the strongest baseline candidate, lost 26.21 percentage points of annualized return;
  this indicates that the signal's profitable exposure often occurs before broad participation
  reaches the 50% threshold.
- No instrument passed the 15% complete-month requirement, and no instrument passed the 50%
  annualized requirement. The candidate is not a promotion or live-trading permission.
- Historical quote depth remains `UNKNOWN`; all trades lack full-depth observations.

## Next action

Keep the baseline and this candidate as immutable evidence. Do not lower the return gate or
select a different breadth threshold after seeing the result. A next experiment must address a
different identified mechanism (for example, exposure sizing/turnover economics) and must be
pre-registered with the same frozen universe and monthly gate.
