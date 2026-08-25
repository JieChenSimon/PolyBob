# PB-0040 cross-sectional drawdown recovery candidate

Date: 2026-08-25

## Decision

**Reject the recovery candidate.** The permanent lockout in
`vol_target_10_dd` was replaced by one explicit recovery rule: after a 20%
portfolio drawdown, remain flat for 20 trading bars, then resume at 25% target
exposure until drawdown is below 10%. The change prevents zero-trade lockout,
but it worsens the paired OOS result and is not a strategy improvement.

## Frozen paired contract

- Same current discovery manifest and 27 US-equity instruments
- Same real local daily bars
- Same real `modules.simulation.SimulationService` kernel
- Same signal: lookback 20, top 30%, rebalance every 5 sessions
- Same OOS window: 2025-02-14 through 2026-08-24
- Same 10% stop-loss and five-bar cooldown
- Same cost and isolated $100,000 per-instrument capital contract
- Only changed field: risk policy (`vol_target_10` versus
  `vol_target_10_dd_recovery`)

## Paired result

| Measure | Baseline `vol_target_10` | Recovery candidate | Change |
|---|---:|---:|---:|
| Mean instrument return | 6.33% | 4.28% | -2.05 pp |
| Median instrument return | 2.50% | 2.50% | 0.00 pp |
| Positive instruments | 16 / 27 | 14 / 27 | -2 |
| Stable instruments | 13 / 27 | 13 / 27 | 0 |
| Median max drawdown | 17.75% | 19.06% | +1.31 pp |
| Total trades | 446 | 434 | -12 |
| Target-gate passes | 0 / 27 | 0 / 27 | 0 |

The recovery rule fixed the specific zero-trade pathology (`zero=0/27`) but did
not improve return, drawdown, stability, or target coverage. It therefore must
not be promoted or used as evidence that the underlying signal is profitable.

## Engineering change

The new policy is named `vol_target_10_dd_recovery`; the old
`vol_target_10_dd` behavior remains unchanged for reproducibility. The policy
parameters are explicit constants, are bounded so exposure never exceeds the
signal, and have a unit test proving that the recovery path eventually resumes
with reduced exposure rather than remaining permanently inactive.

## Research conclusion

The result reinforces the prior attribution: the cross-sectional signal's
positive mean is tail-driven and does not survive a universal per-instrument
target gate. Further tuning of this risk-policy family is not justified until
the data snapshot and executable quote-depth contracts are strengthened.
Promotion remains `BLOCKED`.
