# PB-0040 instrument/strategy gate matrix — 2026-08-25

## Decision

The current real-data evidence set contains no promotion candidate. The unified fail-closed
matrix covers 80 instruments and 653 instrument-strategy rows:

- `PASS`: 0
- `FAIL`: 167
- `UNKNOWN`: 486
- Promotion: `BLOCKED`

Artifact: `data/instrument_strategy_evidence.json`.

## Coverage

| Domain | Evidence rows |
|---|---:|
| US equity | 405 |
| A-share | 104 |
| Crypto | 144 |

The matrix includes the prior domain candidates plus the latest frozen 2022–2026 US
cross-sectional momentum, breadth-filter, and standalone mean-reversion replays, as well as
the quality-gated deep-drawdown kernel. Missing target evidence remains `UNKNOWN`; it is never
converted to zero or a pass.

## Strategy-level status

| Strategy family | Rows | PASS | FAIL | UNKNOWN |
|---|---:|---:|---:|---:|
| US cross-sectional candidate | 27 | 0 | 27 | 0 |
| A-share cross-sectional candidate | 8 | 0 | 8 | 0 |
| Deep-drawdown rebound | 564 | 0 | 114 | 450 |
| Crypto signed momentum | 18 | 0 | 0 | 18 |
| Crypto walk-forward momentum | 18 | 0 | 0 | 18 |
| Frozen US momentum | 6 | 0 | 6 | 0 |
| US breadth candidate | 6 | 0 | 6 | 0 |
| US standalone mean reversion | 6 | 0 | 6 | 0 |

## Interpretation

The failures are not a reason to weaken the requested annual 50% and complete-month 15% gates.
They show that the currently available price-only and row-level-quality strategies do not have
verified target-achieving evidence after modeled costs. The large `UNKNOWN` block is mostly
deep-drawdown events without enough complete OOS observations or with unresolved strict PIT,
survivorship, and historical executable quote/depth evidence.

## Next executable work

1. Materialize a strict historical PIT fundamentals contract with filing-level availability and
   restatement lineage, not only current-time collection snapshots.
2. Add a point-in-time listed/delisted universe and delisting-exit prices for each equity sleeve.
3. Acquire or materialize historical bid/ask/depth observations linked to every simulated fill.
4. Re-run the frozen strategy matrix unchanged once all three evidence gates are READY; only then
   evaluate a new quality/deep-drawdown candidate.
