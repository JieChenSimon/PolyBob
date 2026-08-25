# PB-0040 evidence-readiness audit — 2026-08-25

## Decision

The current strategy evidence remains research-only. The local datasets are useful for causal
diagnostics, but they are not yet sufficient for a promotion-grade historical backtest.

## Measured local state

| Dataset | Symbols | Rows | Event coverage | First fetch | Strict historical PIT |
|---|---:|---:|---|---|---|
| daily_bars | 2,855 | 10,671,879 | 2021-07-26–2026-08-24 | 2026-07-27 | `false` |
| fundamentals | 95 | 8,527 | 1989-12-31–2026-08-20 | 2026-08-25 | `false` |

The historical daily bars were collected in 2026 and therefore do not prove that the current
surviving universe was knowable at each historical date. The fundamentals mirror has filing and
acceptance metadata, but its dataset contract is still `collected_observation_time`; current
retrieval is not itself historical PIT evidence.

For the quality-gated US candidates, the local read showed repeated observations for nearly every
event date (`restatements` reported for NVDA 68, INTC 69, AMD 65, MRVL 21, SNDK 7, MU 64, WDC
68). The latest-vintage selection is deterministic, but a promotion gate still needs the full
vintage lineage and an as-of reconstruction test rather than treating the latest row as history.

## Missing execution evidence

No local historical BBO/depth/order-book files were found under `data/`. Simulation runs record
quote provenance and depth quality when supplied, but the daily-bar deep-drawdown and standalone
equity replays had no linked historical quote observations. Their modeled fees and penalties are
stress assumptions, not proof of executable fills.

## Required data products before promotion

1. **Strict PIT fundamentals:** filing-level `announcement_at`/`accepted_at`, raw accession
   hashes, every restatement vintage, and a query that reconstructs the latest known row at any
   decision timestamp.
2. **Survivorship-free universe:** listing, delisting, suspension, corporate-action and final
   executable exit records, all with effective and observed timestamps.
3. **Historical execution tape:** timestamped bid/ask, depth, spread, source, sequence/provenance,
   and a fill-link key for every simulated trade; missing depth must remain no-fill/UNKNOWN.
4. **Revalidation:** rerun the frozen 48-case deep-drawdown matrix and the complete 653-row
   instrument-strategy gate matrix without changing signal parameters.

Until these products are READY, the observed positive events cannot be promoted or extrapolated
to the annual 50% / complete-month 15% target.
