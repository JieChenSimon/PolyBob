# PolyBob runtime boundaries

PolyBob is a research-first local market workbench. It does not present
unwired infrastructure as production capability.

## Authority

- SQLite stores runtime state, jobs, intent/order/fill ledgers, audit events,
  and replayable feature snapshots.
- Parquet stores reusable historical and point-in-time datasets. Research
  reads must use the `as_of` contract rather than operational state.
- Raw order-book logging is optional and bounded by retention days and row
  count; it is disabled by default to prevent unbounded disk growth.
- Paper broker simulation never submits to a venue. Real execution remains
  behind capability, promotion, and portfolio-risk gates.

## Runtime and degradation

The default API starts only core workbench services. Forecasting, pair features,
altcoin discovery, automated trading, and paper execution require explicit
`ENABLE_LAB_*` switches. `/api/runtime/status` exposes actual storage, data,
queue, model, and risk state. `unknown` is never treated as available.

External data that is stale, incomplete, duplicated, or failed produces an
explicit degraded/unknown/blocked state. Task runs have idempotency keys,
retry/timeout state, and restart recovery; feature snapshots have stable IDs
and can be replayed.
