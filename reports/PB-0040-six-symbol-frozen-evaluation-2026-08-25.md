# PB-0040 six-symbol frozen evaluation

Date: 2026-08-25

## Purpose

The previous four-fold diagnostic found six symbols that were positive in every
fold. This replay evaluates those symbols with isolated $100,000 accounts while
keeping the signal universe unchanged at the full 26-symbol `US_LIQUID` set.
This prevents re-ranking a six-symbol universe after seeing the OOS result.

Input snapshot: `5bc5c9ab66fc19e06fb199133041e78bd7b1780104e7f6bfed8df23c7548623b`.

## Frozen contract

- Signal: lookback 60, top 30%, rebalance 10 sessions, long-only
- Risk policy: `vol_target_10`
- Evaluation symbols: AAPL, AMD, GOOGL, INTC, MRK, XOM
- OOS window: 2025-02-14 through 2026-08-24
- Real local daily bars and real `SimulationService` ledger/fill path
- Isolated capital: $100,000 per symbol
- Historical executable depth: UNKNOWN

## Results

| Symbol | Total return | Annualized estimate | Max drawdown | Trades | Stability | Target |
|---|---:|---:|---:|---:|---|---|
| AAPL | 19.12% | 12.18% | 12.80% | 4 | PASS_STABLE | FAIL |
| AMD | 160.15% | 88.04% | 26.04% | 6 | PASS_STABLE | FAIL monthly |
| GOOGL | 29.33% | 18.63% | 26.56% | 6 | PASS_STABLE | FAIL monthly |
| INTC | 151.13% | 83.71% | 35.04% | 8 | PASS_STABLE | FAIL monthly |
| MRK | 33.39% | 20.96% | 12.77% | 4 | PASS_STABLE | FAIL monthly |
| XOM | 17.25% | 11.08% | 16.04% | 4 | PASS_STABLE | FAIL |

Although AMD and INTC have high annualized estimates, both fail the required
15% complete-month condition repeatedly and carry large drawdowns. They are not
valid exceptions to the per-instrument gate. The other four do not reach the
annual target either. Therefore target passes are **0/6** and Promotion remains
`BLOCKED`.

## Interpretation

The six-symbol result confirms that four-fold positivity was descriptive and
not sufficient evidence of a stable target-achieving strategy. The low trade
counts (4–8 per symbol) also make the annualized estimates fragile; they should
not be extrapolated into a live return promise. The next valid experiment must
extend the frozen OOS calendar or add independent execution evidence, not tune
these six symbols after observing the result.
