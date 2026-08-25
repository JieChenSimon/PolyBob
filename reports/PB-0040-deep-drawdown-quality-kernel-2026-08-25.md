# PB-0040 deep-drawdown quality-gated kernel replay

Date: 2026-08-25

## Decision

**Reject for promotion and keep as research-only evidence.** The row-level
quality gate reduced the candidate universe to the four symbols that actually
contained the 25 PASS events in the current local evidence: NVDA, INTC, AMD,
and MRVL. The controlled replay did not produce enough completed OOS events to
establish a profitable strategy.

## Run contract

- Real local daily bars only
- Real `modules.simulation.SimulationService` fill, risk, position, and ledger
  path
- Symbols: NVDA, INTC, AMD, MRVL
- Drawdown trigger: first close crossing at least 50% below the prior expanding
  close peak
- Row-level fundamental quality filter: PASS event dates only
- Probe fraction: 25%
- Confirmation bars: 0
- Holding period: 21 sessions
- Cost stress: 1x declared domain round-trip cost
- Four total cases (one per symbol)

The replay remained explicitly non-promotable because row-level quality is not
the same as point-in-time survivorship-safe fundamentals, and historical
executable quote depth is not available.

## Results

| Symbol | Signal count | Complete OOS events | OOS mean net return | Quality gate | Promotion |
|---|---:|---:|---:|---|---|
| NVDA | 18 | 0 | UNKNOWN | PASS event date | BLOCKED |
| INTC | 18 | 0 | UNKNOWN | PASS event date | BLOCKED |
| AMD | 24 | 1 | 0.060% | PASS event date | BLOCKED |
| MRVL | 12 | 0 | UNKNOWN | PASS event date | BLOCKED |

There is no statistically meaningful OOS sample here. The single AMD result
is not evidence of edge and cannot support the requested annual or monthly
return targets. No instrument passed the target gate.

## Engineering finding and fix

The first unrestricted attempt expanded to 34,260 cases by combining the full
stored market universe with all holding periods and cost multiples. It pushed
CPU usage above the project's resource budget and was terminated before any
evidence was accepted. The runner now:

1. restricts the default universe to symbols with an actual drawdown event;
2. restricts quality-only runs to symbols with at least one row-level quality
   PASS event;
3. accepts explicit comma-separated holding periods and cost multiples; and
4. fails closed when the case count exceeds `--max-cases` (default 120).

This makes the pipeline reproducible and bounded without silently dropping
requested cases. Large matrices now require an explicit operator decision to
raise the limit.

## Next action

Do not tune this sample to manufacture a return. First materialize accepted-at
point-in-time fundamentals and historical executable quote/depth evidence. If
those gates become READY, rerun the same four symbols with 21/63/126/252-day
holds and cost stress; otherwise retain this branch as UNKNOWN/BLOCKED.

## Verification

- `tests/test_deep_drawdown_kernel_replay.py`: 2 passed
- Controlled replay completed with 4 cases
- `real_data_only` and shared SimulationService kernel retained
- Promotion remained BLOCKED
