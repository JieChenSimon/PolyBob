# PB-0039 BTC 5-minute low-frequency momentum kernel replay

Date: 2026-08-25

## Decision

**Reject and keep `NO_EDGE`.** A small pre-registered dual-moving-average
family was replayed through the real `SimulationService` using the local real
BTC-USDT data. Every candidate was negative after the declared execution cost
stress. The best candidate did not provide meaningful OOS evidence and none
approached the requested return gate.

## Contract

- Dataset: `data/datasets/parts/btc_1m_bars_clean_v2/symbol=BTC-USDT`
- Source: real local OKX-derived bars; no synthetic prices
- Aggregation: causal 1-minute bars resampled to 5-minute observations
- Coverage: 2026-08-03 19:30 UTC through 2026-08-24 18:55 UTC
- Independent calendar days: 22
- Strategy: `momentum_dualma_v1`, fast/slow SMA on causal mid-price snapshots
- Pre-registered parameter family: `(12,36)`, `(36,72)`, `(12,72)` bars
- Cost multiples: 1x, 2x, 3x of 20 bps fee plus 10 bps mid-price penalty
- Position fraction: 10% of initial capital; shorting enabled
- Cooldown: 30 minutes; minimum rebalance: 50 bps
- Kernel: real `modules.simulation.SimulationService`, fills, positions,
  equity and ledger
- Historical executable depth: UNKNOWN; this is not promotion evidence

## Results

| Fast/slow | Cost | Total return | OOS return | Max drawdown | Trades |
|---|---:|---:|---:|---:|---:|
| 12/36 | 1x | -6.77% | -1.80% | 6.91% | 128 |
| 12/36 | 2x | -14.13% | -4.83% | 14.21% | 128 |
| 12/36 | 3x | -21.49% | -8.19% | 21.52% | 128 |
| 36/72 | 1x | -3.32% | +0.11% | 3.49% | 76 |
| 36/72 | 2x | -7.56% | -1.30% | 7.65% | 76 |
| 36/72 | 3x | -11.80% | -2.81% | 11.82% | 76 |
| 12/72 | 1x | -5.62% | -1.41% | 5.63% | 103 |
| 12/72 | 2x | -11.42% | -3.57% | 11.43% | 103 |
| 12/72 | 3x | -17.22% | -5.92% | 17.22% | 103 |

The isolated OOS return of +0.11% for 36/72 is one short 22-day sample and is
not a positive strategy result. The return-target evaluator correctly remained
`UNKNOWN` because the history does not contain 12 complete months.

## Attribution

1. The lower-frequency filter reduced the catastrophic turnover seen in the
   previous direction proxy, but the signal itself still had negative realized
   edge in the kernel.
2. Cost stress is monotonic: every additional cost multiple materially worsens
   return, so the small positive preliminary low-cost vector result was not
   robust to the paper-fill cost contract.
3. The best candidate's OOS sample is too short and has no executable depth
   linkage; it cannot be promoted or extrapolated to the 50% annual / 15%
   complete-month target.

## Resource verification

The initial implementation reached approximately 95% single-process CPU during
bar replay and was terminated before evidence acceptance. The runner now uses
an average process CPU throttle targeting 45%; the completed nine-case run was
observed at approximately 42–45% CPU and left no replay database artifacts.

## Next action

Do not continue tuning this BTC 5-minute price-only family. A new BTC candidate
requires a genuinely different source of edge—such as verified executable
market/quote data and a pre-registered expected-value model—plus a longer
history. Until then, preserve `NO_EDGE` and do not permit automated live use.
