# PB-0040 PIT-quality deep-drawdown confirmation candidate — 2026-08-25

## Decision

**Reject for promotion.** The candidate combined the existing row-level PIT quality gate with
a 25% initial probe, five-session confirmation, and the fixed 0/5/20-session tranche schedule.
All 48 cases completed through the real `SimulationService`, but the OOS event sample remained
insufficient and the only symbol with a completed OOS event produced low single-digit returns.

## Contract

- Symbols with at least one row-level quality-approved event: NVDA, INTC, AMD, MRVL
- Symbols without a quality-approved event: SNDK, MU, WDC; no trade permitted
- Trigger: first causal close at least 50% below prior expanding close peak
- Entry: 25% probe, confirmation 5 sessions, then fixed tranches at 0/5/20 sessions
- Holds: 21/63/126/252 sessions
- Cost stress: 1x/2x/3x declared US-equity round-trip cost
- Capital cap: 5% NAV, real fill/position/equity/ledger path
- Historical quote depth, global PIT survivorship and delisting exits: `UNKNOWN`
- Artifacts: `data/deep_drawdown_kernel_quality_confirm5.json` and its progress file

## OOS results

| Symbol | OOS complete events | 21d net | 63d net | 126d net | 252d net | Quality status |
|---|---:|---:|---:|---:|---:|---|
| NVDA | 0 | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | PASS_EVENT_DATE_GATE |
| INTC | 0 | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | PASS_EVENT_DATE_GATE |
| AMD | 1 | -0.03% | 2.82% | 2.31% | 3.79% | PASS_EVENT_DATE_GATE |
| MRVL | 0 | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | PASS_EVENT_DATE_GATE |

The displayed AMD figures are at 1x cost. Cost stress was monotonic and reduced each AMD
estimate at 2x and 3x. One OOS event cannot support an annual or monthly claim, and none of the
four instruments approaches the 50% annual / 15% complete-month target gate.

## Attribution

1. The confirmation/tranche rule reduces the chance of immediately buying a falling knife, but
   it also leaves almost no independent OOS events in the available history.
2. The row-level quality gate is not a complete point-in-time fundamental or survivorship gate;
   `PASS_EVENT_DATE_GATE` must not be interpreted as `PIT_READY`.
3. The historical daily bars have no linked executable quote/depth observations. All cases remain
   research-only and blocked from live or automated use.

## Next executable evidence

Do not tune confirmation bars, tranche delays, or holding periods on this sparse OOS sample.
Before another deep-drawdown optimization, materialize strict announcement-time fundamentals,
survivorship/delisting coverage, and historical executable quotes. Once those are READY, rerun
this frozen 48-case matrix unchanged and require at least 20 independent event clusters before
any promotion decision.
