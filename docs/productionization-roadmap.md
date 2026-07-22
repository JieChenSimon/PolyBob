# PolyBob Productionization Roadmap

## Objective

Turn PolyBob from a feature-rich prototype into a trustworthy personal investment
workbench. The core path must support one reproducible loop:

1. Ingest and validate market and fundamental data.
2. Produce a versioned investment decision.
3. Apply the decision to a real or paper portfolio.
4. Enforce portfolio and execution risk limits.
5. Persist every input, decision, action, and outcome.
6. Review whether the decision and model performed as expected.

Anything that does not meet the core acceptance gates remains in `lab`.

## Core Acceptance Gates

Every core capability must satisfy all six gates:

| Gate | Required evidence |
| --- | --- |
| Real input | Input comes from an identified provider and includes source time, ingest time, and freshness status. |
| Single implementation | Live analysis and backtest use the same calculation code and parameter schema. |
| Persistent state | Restarting the API does not lose portfolios, decisions, intents, orders, or review history. |
| Traceable output | Every conclusion records model version, data version, parameters, reasons, and invalidation conditions. |
| Failure behavior | Stale, incomplete, inconsistent, or unavailable data blocks or downgrades the conclusion explicitly. |
| Automated validation | Unit, integration, restart-recovery, and representative historical tests cover the capability. |

## Workstreams

### P0: Product Contract

- [ ] Define the single daily workflow: review -> decide -> size -> execute -> review.
- [ ] Define which screens belong to `core`, `lab`, and `archive`.
- [ ] Define decision states and their exact semantics.
- [ ] Define what PolyBob may claim when data is delayed, incomplete, or unavailable.
- [ ] Remove or visibly label conclusions that are generated from mock inputs.

Acceptance:

- A user can identify today's highest-priority decision within 30 seconds.
- Every displayed recommendation can be opened to inspect its evidence and provenance.
- No simulated metric is presented as a measured fact.

### P1: Persistent Domain Foundation

- [ ] Select the single API entrypoint and retire the duplicate runtime path.
- [ ] Implement database connection and migration management.
- [ ] Persist instruments, portfolios, positions, cash, transactions, decisions, intents, baskets, orders, fills, and reviews.
- [ ] Add idempotency keys and restart recovery for write operations.
- [ ] Add an append-only audit event table.
- [ ] Add repository interfaces so services do not store authoritative state in dictionaries.

Acceptance:

- API restart preserves all authoritative state.
- Repeating a submitted command does not create duplicate economic actions.
- Every portfolio-changing action can be reconstructed from the audit trail.

### P2: Securities Data Platform

#### Deferred: Futu OpenAPI

Futu OpenAPI has been evaluated as a future parallel provider for realtime
quotes, push K-lines, fundamentals, valuation, ownership, and research data.
Implementation is intentionally deferred: do not install Futu OpenD or the
`futu-api` SDK, and do not add Futu to the default startup or runtime path yet.

Reconsider this integration only when the operator is ready to keep the Futu
OpenD GUI logged in and running on `127.0.0.1:11111`. Any future integration
must use a persistent backend connection, keep trading disabled by default,
reuse the vendor-provided skills under `skills/`, and treat current online Futu
permission and quota documentation as authoritative when it differs from the
bundled skill documentation.

- [ ] Build a canonical instrument master for US equities and A-shares.
- [ ] Persist daily bars with adjustment status and provider metadata.
- [ ] Persist quote snapshots with market time, ingest time, freshness, and provider.
- [ ] Add trading calendars, symbol aliases, delisting status, and corporate actions.
- [ ] Add data validation for duplicates, gaps, impossible prices, stale quotes, and adjustment discontinuities.
- [ ] Add fundamental statements and normalized financial metrics.
- [ ] Add provider fallback and explicit degraded-data states.

Acceptance:

- The same symbol resolves consistently across quote, bar, fundamental, portfolio, and decision APIs.
- Historical calculations are reproducible for a requested as-of date.
- Stale or invalid data cannot silently generate an actionable recommendation.

### P3: Versioned Equity Decision Engine

- [ ] Replace symbol-derived mock scores with measured features.
- [ ] Implement a first versioned model using trend, quality, growth, valuation, balance-sheet, and risk features.
- [ ] Separate measured facts, model scores, portfolio constraints, and final actions.
- [ ] Store model version, feature snapshot, thresholds, and explanation for every decision.
- [ ] Define action invalidation conditions and a next-review trigger.
- [ ] Make action prices derive from volatility, support/resistance, valuation, and portfolio constraints rather than fixed percentages.

Acceptance:

- Running the same model version on the same as-of dataset produces the same decision.
- Every score is traceable to a stored raw value and transformation.
- The system can explain what changed between two consecutive decisions.

### P4: Research and Backtest Protocol

- [ ] Make live feature computation and backtest feature computation share one implementation.
- [ ] Implement point-in-time universe membership and fundamental availability.
- [ ] Handle splits, dividends, delistings, suspensions, fees, slippage, and liquidity constraints.
- [ ] Add train/validation/test periods and walk-forward evaluation.
- [ ] Add benchmark, turnover, exposure, drawdown duration, and capacity metrics.
- [ ] Store immutable backtest runs with code/model/data versions.
- [ ] Add overfitting, lookahead, survivorship, and parameter-stability checks.

Acceptance:

- A backtest run can be reproduced from its run identifier.
- No future information is available to a historical decision.
- Results include out-of-sample performance and failure regimes, not only aggregate returns.

### P5: Portfolio and Risk Engine

- [ ] Import or manually maintain real portfolio positions, costs, cash, and transactions.
- [ ] Implement target sizing based on portfolio NAV and risk budget.
- [ ] Add single-name, sector, market, currency, liquidity, and correlation limits.
- [ ] Add drawdown and daily-loss controls.
- [ ] Add earnings/event risk and stale-data gates.
- [ ] Add pre-trade and post-trade risk checks using the same portfolio state.
- [ ] Add a kill switch and an explicit manual override audit record.

Acceptance:

- Recommendations use actual holdings and available cash.
- A blocked action reports the exact risk rule and required remediation.
- Portfolio exposure and PnL reconcile against the transaction ledger.

### P6: Paper Execution and Review

- [ ] Implement a deterministic paper broker with order lifecycle and fills.
- [ ] Persist submitted, acknowledged, partially filled, filled, cancelled, and rejected states.
- [ ] Reconcile orders, fills, positions, cash, and fees after every action.
- [ ] Add decision-to-order linkage.
- [ ] Add daily review: expected result, actual result, attribution, and operator notes.
- [ ] Add weekly model and portfolio review reports.

Acceptance:

- Every fill maps to one order, intent, decision, portfolio, and model version.
- Restart recovery resumes without duplicating orders or losing fills.
- The review surface can distinguish model error, execution error, data error, and operator override.

### P7: Operating Reliability

- [ ] Add structured health checks for providers, ingestion, database, jobs, and API.
- [ ] Add data freshness and failed-job alerts.
- [ ] Add scheduled ingestion and recomputation jobs.
- [ ] Add backup and restore verification.
- [ ] Add CI for backend tests, dashboard build, migrations, and integration contracts.
- [ ] Add a production startup mode that never builds while a dev server is running.

Acceptance:

- A failed provider or stale dataset is visible before it affects a recommendation.
- A clean machine can start the core system from documented commands.
- Backup restore and restart recovery are tested, not assumed.

## Initial Delivery Sequence

The first implementation tranche should be narrow:

1. Mark mock equity conclusions as `lab` until replaced.
2. Establish one API entrypoint and persistent database infrastructure.
3. Add the instrument master, portfolio ledger, and decision audit models.
4. Persist daily bars and quote provenance for a small supported universe.
5. Implement one versioned equity model for that universe.
6. Run the same model through a point-in-time backtest.
7. Connect its recommendation to the paper portfolio and review journal.

Do not expand coverage until this vertical slice passes all core acceptance gates.
