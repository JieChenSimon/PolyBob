# PB-0040 cross-sectional volatility-cap sensitivity

Date: 2026-08-25

## Decision

**Reject and do not promote.** This was a pre-registered sensitivity run on
real local US-equity data through the real `modules.simulation.SimulationService`
kernel. Adding an annualized-volatility ceiling of 80% reduced the performance
of the current 20-day / top-30% / 5-day rebalance candidate and did not satisfy
the return, execution-evidence, or research promotion gates.

## Reproducible contract

- Domain: `us_equity`
- Requested and actual window: 2025-02-14 through 2026-08-24
- Instruments analyzed: 27, after 7 quality rejections
- Lookback: 20 sessions
- Selection: top 30% cross-sectional score
- Rebalance: every 5 sessions
- Risk policy: `vol_target_10`
- Tail-risk sensitivity: 20-session annualized volatility capped at 80%
- Capital: isolated $100,000 per instrument
- Explicit costs: 5 bps fee and 10 bps mid-price penalty in the shared
  simulation kernel
- Execution evidence: all 414 trades had `missing_depth`; full historical
  executable quote depth remains unknown

The machine-readable source was written to
`/tmp/polybob_us_oos_candidate_20_30_5_vol08.json` during the run. It is an
ephemeral replay artifact and is not treated as a durable project dataset.

## Results

| Measure | Result |
|---|---:|
| Mean instrument total return | 2.37% |
| Median instrument total return | 2.50% |
| Positive instruments | 16 / 27 |
| Stable instruments | 13 / 27 |
| Instruments passing the 50% annual / 15% complete-month gate | 0 / 27 |
| Mean instrument max drawdown | 22.40% |
| Median instrument max drawdown | 17.75% |
| Mean instrument Sharpe | 0.154 |
| Total trades | 414 |
| Promotion | BLOCKED |

The candidate's aggregate OOS result is therefore positive in the arithmetic
mean, but economically weak, unstable as a universal per-instrument system,
and not executable-grade because quote depth is unresolved. A positive mean is
not evidence that each instrument can meet the user's target.

## Comparison and interpretation

The existing un-capped 20/30/5 sensitivity in the full-universe evidence had
approximately 5.17% median per-instrument return and 10.54% mean return. The
80% volatility ceiling produced 2.50% median and 2.37% mean return here. This
indicates that this particular cap is suppressing exposure during profitable
high-volatility regimes without solving the core problems: weak per-instrument
returns, large drawdowns, monthly target failure, and unknown depth.

The result does not prove volatility controls are useless. It only rejects this
threshold and this contract for promotion. Future risk controls must be
compared against the same frozen universe, dates, costs, and OOS protocol, and
must pass per-instrument and execution gates rather than aggregate return
alone.

## Failure causes and next research action

1. The 80% cap is too restrictive for the observed regime and reduces signal
   participation.
2. The base cross-sectional signal still lacks sufficient edge after costs to
   meet the per-instrument target.
3. The dataset has no linked historical depth, so even positive replay results
   cannot be promoted to live use.
4. The next justified branch is not more blind parameter search. It is to add
   an independently auditable, point-in-time quality/fundamental gate and test
   staged deep-drawdown entries only where the global data-quality contract is
   `READY`; otherwise the result must remain `UNKNOWN/BLOCKED`.

## Verification

- Replay completed without runtime failure.
- `real_data_only: true`.
- `research_only: true`.
- Promotion remained `BLOCKED` as required by unresolved execution depth and
  incomplete research gates.
