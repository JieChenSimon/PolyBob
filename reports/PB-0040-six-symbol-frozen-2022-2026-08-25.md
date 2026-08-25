# PB-0040 six-symbol frozen evaluation — extended OOS

Date: 2026-08-25

## Decision

**Reject for promotion.** Extending the unchanged signal contract to 2022-01-03 through
2026-08-24 increases the evidence to 56 complete calendar months per instrument, but 0/6
instruments satisfy both the annualized-return and every-complete-month target gates. The
result is therefore not a validated path to the requested return objective.

## Frozen contract

- Signal universe: fixed 26-symbol `US_LIQUID`; no re-ranking of the evaluation universe
- Evaluation symbols: AAPL, AMD, GOOGL, INTC, MRK, XOM
- Signal: lookback 60, top 30%, rebalance every 10 sessions, long-only
- Risk policy: `vol_target_10`
- Costs: the same `SimulationService` fee and mid-price penalty contract as the prior run
- Capital: isolated $100,000 per instrument
- Data: real local US daily bars; input snapshot `5bc5c9ab66fc19e06fb199133041e78bd7b1780104e7f6bfed8df23c7548623b`
- Execution depth: `UNKNOWN`; every recorded trade had `missing_depth`
- Full replay artifact: `data/cross_sectional_six_frozen_2022.json`

## Results

| Symbol | Total return | Annualized | Max DD | Closed trades | Months ≥15% | Stability | Promotion |
|---|---:|---:|---:|---:|---:|---|---|
| AAPL | 4.91% | 1.07% | 33.67% | 8 | 0/56 | PASS_STABLE | BLOCKED |
| AMD | 332.71% | 37.26% | 35.79% | 8 | 8/56 | PASS_STABLE | BLOCKED |
| GOOGL | -0.92% | -0.20% | 26.56% | 9 | 1/56 | PASS_STABLE | BLOCKED |
| INTC | 86.25% | 14.38% | 48.18% | 13 | 6/56 | FAIL_UNSTABLE | BLOCKED |
| MRK | 56.03% | 10.09% | 16.31% | 8 | 1/56 | PASS_STABLE | BLOCKED |
| XOM | 32.87% | 6.33% | 33.54% | 9 | 1/56 | PASS_STABLE | BLOCKED |

## Quantitative attribution

1. **Return concentration:** AMD's 332.71% total return is concentrated in the last fold
   (160.15%), while its first two folds were 32.0% and 25.4%; its annualized estimate remains
   below 50%. INTC is a stronger instability warning: -5.5%, -21.5%, then +151.1% across the
   three chronological folds.
2. **Monthly gate failure:** the strategy has sparse exposure and long zero-return months;
   positive annual compounding cannot be translated into a 15% return in every complete month.
   This is a structural mismatch with the requested gate, not a rounding issue.
3. **Risk:** maximum drawdown is 16.31%–48.18%, so the high-return observations are not low-risk
   exceptions. No drawdown guard was added after seeing this run.
4. **Execution:** explicit fees plus mid-price penalty were charged, but historical quote depth
   was unavailable for all trades. The results are research-only and cannot be treated as live
   executable evidence until depth is supplied.

## Next constrained experiment

Keep this baseline immutable. The next candidate must be pre-registered before replay and must
address the identified failure mechanism rather than select AMD/INTC after the fact: a causal
market-regime/exposure filter with a fixed maximum drawdown budget, evaluated on the same six
symbols and full signal universe, with the 56-month monthly gate and the same costs. If it lowers
drawdown but does not improve OOS monthly breadth, reject it; if it improves only one symbol,
do not extrapolate it to the other instruments.
