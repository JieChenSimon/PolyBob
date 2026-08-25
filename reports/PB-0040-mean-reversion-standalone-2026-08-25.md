# PB-0040 standalone mean-reversion candidate — 2026-08-25

## Decision

**Reject.** The pre-registered 20-observation trailing-mean reversion rule was replayed for
each frozen instrument through the real `SimulationService` from 2022-01-03 to 2026-08-24.
It produced materially more turnover and worse return/risk than the frozen cross-sectional
momentum baseline. No instrument passed the requested annual and complete-month gates.

## Contract

- Signal family: long-only mean reversion, independent per instrument
- Entry: close at least 100 bps below the causal trailing 20-observation mean
- Exit: close at or above 50 bps below that mean
- Signal universe: all 26 `US_LIQUID` symbols loaded; evaluation symbols frozen to AAPL, AMD,
  GOOGL, INTC, MRK, XOM
- Risk: `vol_target_10`
- Costs: same fee and mid-price penalty as the frozen baseline
- Window: 2022-01-03 through 2026-08-24, 56 complete months
- Artifact: `data/cross_sectional_six_meanrev20_100_2022.json`
- Input snapshot: `5bc5c9ab66fc19e06fb199133041e78bd7b1780104e7f6bfed8df23c7548623b`
- Historical quote depth: `UNKNOWN`; every trade was recorded as `missing_depth`

## Results

| Symbol | Total return | Annualized | Max DD | Closed trades | Months ≥15% | Stability | Promotion |
|---|---:|---:|---:|---:|---:|---|---|
| AAPL | 16.31% | 3.31% | 20.92% | 50 | 0/56 | PASS_STABLE | BLOCKED |
| AMD | -10.20% | -2.30% | 50.21% | 51 | 2/56 | PASS_STABLE | BLOCKED |
| GOOGL | 13.13% | 2.70% | 25.63% | 53 | 0/56 | FAIL_UNSTABLE | BLOCKED |
| INTC | -22.94% | -5.47% | 60.38% | 59 | 1/56 | FAIL_UNSTABLE | BLOCKED |
| MRK | 7.71% | 1.62% | 25.83% | 44 | 0/56 | FAIL_UNSTABLE | BLOCKED |
| XOM | 25.88% | 5.10% | 17.04% | 57 | 0/56 | PASS_STABLE | BLOCKED |

## Attribution

- The trigger buys weakness without a verified fundamental-quality or regime condition. On AMD
  and INTC this repeatedly entered continuing declines; the resulting drawdowns were 50.21% and
  60.38%.
- Turnover was 44–59 closed trades per symbol, compared with 8–13 in the frozen momentum
  baseline. Costs were therefore a first-order loss source, not a minor adjustment.
- Even where total returns were positive, annualized returns stayed below 6% and monthly target
  coverage was effectively zero. There is no evidence that this is a target-achieving edge.

## Next action

Keep this candidate rejected and do not optimize its entry threshold on the observed OOS result.
The next valid experiment must combine a separately frozen quality/PIT condition with a deep-
drawdown event rule, or otherwise explain why the weakness is temporary rather than a continuing
fundamental deterioration. If PIT quality is unavailable, the result must remain `UNKNOWN`, not
be used as a trading filter.
