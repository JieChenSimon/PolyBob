# PolyBob Agent Team Backlog

This backlog is the integrated output of the PolyBob agent team review.

The goal is not to add more screens. The goal is to replace prototype behavior
with a trustworthy personal investment workflow.

## Agent Team

| Role | Responsibility | Primary conclusion |
| --- | --- | --- |
| Product and Investment Workflow Lead | Daily workflow, decision lifecycle, review loop | PolyBob lacks a persistent `case -> decision -> action -> execution -> review` lifecycle. |
| Market Data and Fundamentals Lead | Instruments, quotes, bars, financials, data quality | Current market data is suitable for lab display, not core recommendations. |
| Quant Research and Backtest Lead | Scoring model, backtest protocol, bias controls | Equity decisions and backtest metrics are synthetic and must be isolated. |
| Portfolio, Execution, and Platform Lead | Portfolio ledger, paper broker, risk, persistence, recovery | There is no durable paper account, fill model, ledger, or restart recovery. |

## Shared Non-Toy Rule

A feature can enter `core` only when it has:

1. Real input with provider, market time, ingest time, and freshness status.
2. One implementation shared by live analysis and backtest.
3. Persistent state across API restarts.
4. Traceable output with data version, model version, parameters, and reasons.
5. Explicit failure behavior for stale, missing, or inconsistent data.
6. Automated validation that covers normal and failure paths.

If any item is missing, the feature belongs in `lab`.

## P0: Stop Misleading Core Output

### P0.1 Mark Synthetic Equity Decisions as Lab

Owner: Quant Research Lead + Product Lead

Why:

- The equity page currently derives decision, risk, target weight, Sharpe,
  drawdown, win rate, and similar-state return from deterministic mock logic.
- Real quotes and moving averages are present, but the main action conclusion is
  not a real model output.

Scope:

- `apps/dashboard/components/USEquityAdvisor.tsx`
- `apps/dashboard/components/PrimaryNav.tsx`
- `apps/dashboard/app/us-equities/page.tsx`

Tasks:

- Rename the surface to `Equity Lab` until a real scorer exists.
- Add visible `SYNTHETIC` or `LAB` status to every mock-derived conclusion.
- Disable or downgrade add/trim language when portfolio data is absent.
- Separate measured facts from synthetic demonstrations:
  - measured: quote, day change, moving averages
  - synthetic: decision, current weight, target weight, action levels, backtest
- Remove equity lab from the core Daily Brief priority flow.

Acceptance:

- No page can present mock-derived data as an actionable recommendation.
- The UI clearly states that current equity conclusions are synthetic.
- Real market data remains visible but cannot imply a real portfolio action.

### P0.2 Replace Zero-Risk Defaults with Unknown States

Owner: Portfolio, Execution, and Platform Lead

Why:

- Risk pages currently show nominal/zero exposure when the real portfolio ledger
  does not exist.
- Unknown risk must never be displayed as safe risk.

Scope:

- `apps/api/main.py`
- `apps/dashboard/components/RiskOpsOverview.tsx`
- `apps/dashboard/components/OverviewSummary.tsx`

Tasks:

- Add `portfolio_status: not_configured | ready | stale | error`.
- Return `null` rather than `0` for unavailable exposure, leverage, PnL, and
  risk budget.
- Surface `not configured` in the UI.
- Block actionable language when `portfolio_status !== ready`.

Acceptance:

- A missing portfolio never renders as zero exposure.
- Overview and Risk pages explain what is missing.

### P0.3 Pick One API Entrypoint

Owner: Platform Lead

Why:

- `apps/api/main.py` and `services/api_server/main.py` overlap and diverge.
- The old API can bypass current lab guard behavior.

Scope:

- `services/api_server/main.py`
- `services/api_server/run.sh`
- `README.md`
- `start.sh`
- `start-all.sh`

Tasks:

- Declare `apps.api.main` as the only core API entrypoint.
- Move the old API under `archive` or make it fail fast with a clear message.
- Update docs and startup scripts.
- Add a test that old lab entrypoints cannot start accidentally.

Acceptance:

- There is one documented API runtime.
- Startup scripts and README do not point to conflicting runtimes.

## P1: Persistent Domain Foundation

### P1.1 Add a Local Fact Store

Owner: Platform Lead

Why:

- Core entities are currently held in process dictionaries.
- Restarting the API loses intents, baskets, orders, and paper state.

Recommended first implementation:

- SQLite WAL for personal single-operator mode.
- Keep Postgres/Timescale as future optional deployment, not the default
  blocker.

Scope:

- `libs/db/`
- `libs/config.py`
- `apps/api/main.py`
- tests under `tests/`

Tables:

- `accounts`
- `investment_cases`
- `decisions`
- `portfolio_actions`
- `intents`
- `baskets`
- `basket_legs`
- `orders`
- `fills`
- `ledger_entries`
- `positions`
- `reviews`
- `audit_events`

Tasks:

- Create DB engine/session helpers.
- Add migration/bootstrap script.
- Add repository interfaces for cases, intents, baskets, orders, fills, and
  ledger entries.
- Add append-only audit events.
- Add restart recovery tests.

Acceptance:

- API restart preserves cases, decisions, intents, orders, fills, and positions.
- Portfolio state can be rebuilt from ledger entries.
- Commands use idempotency keys.

### P1.2 Build Investment Case Lifecycle

Owner: Product Lead + Platform Lead

Why:

- The system has signals and intents, but no durable research case that connects
  thesis, evidence, decision, action, execution, and review.

Scope:

- `libs/schemas/`
- `services/`
- `apps/api/main.py`
- dashboard pages/components

Core object:

```text
InvestmentCase
  -> SignalSnapshot
  -> Decision
  -> PortfolioAction
  -> Intent
  -> Basket
  -> Order
  -> Fill
  -> Position
  -> Review
```

API:

- `POST /api/cases`
- `GET /api/cases`
- `GET /api/cases/{case_id}`
- `PATCH /api/cases/{case_id}`
- `POST /api/cases/{case_id}/decisions`
- `POST /api/decisions/{decision_id}/approve`
- `POST /api/decisions/{decision_id}/reject`
- `POST /api/cases/{case_id}/reviews`

Acceptance:

- A case can be created from a market, updated with evidence, approved into an
  action, and later reviewed.
- Every downstream object can link back to `case_id`.

### P1.3 Convert Daily Brief into a Work Queue

Owner: Product Lead

Why:

- The homepage currently shows status counters instead of today's required work.

Scope:

- `apps/dashboard/app/overview/page.tsx`
- `apps/dashboard/components/PersonalBrief.tsx`
- `apps/dashboard/components/OverviewSummary.tsx`
- API summary endpoints

Queues:

- `Needs Research`
- `Needs Decision`
- `Needs Action`
- `Needs Review`

Each item needs:

- reason
- priority
- deadline or review due time
- current exposure
- next action
- link to the case

Acceptance:

- Opening the dashboard immediately answers what the operator should do next.
- Completing an item removes or moves it to the next queue.

## P2: Securities Data and Fundamentals

### P2.1 Move Equity Universe Out of Frontend Arrays

Owner: Market Data Lead

Why:

- The equity universe is currently a static frontend list.
- There is no canonical instrument ID, listing, alias, exchange, delisting, or
  security type.

Scope:

- new data models under `libs/`
- API under `apps/api/main.py`
- `apps/dashboard/components/USEquityAdvisor.tsx`

Tables:

- `instrument`
- `listing`
- `symbol_alias`
- `trading_calendar`
- `provider_entitlement`

API:

- `GET /api/instruments/resolve`
- `GET /api/instruments/search`
- `GET /api/instruments/watchlist`

Acceptance:

- Search uses backend canonical instrument data.
- One instrument resolves consistently across quotes, bars, fundamentals,
  portfolio, and decisions.

### P2.2 Persist Quotes and Daily Bars with Provenance

Owner: Market Data Lead

Why:

- Next.js routes currently fetch third-party data directly and do not store raw
  payload, quality status, or dataset versions.

Scope:

- `apps/dashboard/app/api/us-equities/quotes/route.ts`
- `apps/dashboard/app/api/equities/technicals/route.ts`
- new Python ingest jobs
- DB tables

Tables:

- `ingest_run`
- `raw_payload`
- `quote_snapshot`
- `daily_bar`
- `quality_check_result`
- `dataset_version`

Response fields:

- `provider`
- `provider_market_time`
- `ingested_at`
- `freshness_status`
- `delay_seconds`
- `quality_flags`
- `coverage`

Acceptance:

- Stale or failed quotes cannot silently fall back to mock prices.
- Daily bars include OHLCV, adjustment status, provider, market time, and ingest
  time.
- Moving averages are computed from stored bars, not directly from page routes.

### P2.3 Add Data Quality Gates

Owner: Market Data Lead

Checks:

- duplicate bars
- missing trading days
- impossible prices
- stale quotes
- split/adjustment discontinuities
- provider disagreement
- unsupported exchanges
- empty or partial provider response

Acceptance:

- Any failed gate marks the dataset degraded.
- Degraded datasets block core recommendations.

### P2.4 Establish Free Data Boundaries

Owner: Market Data Lead + Product Lead

Policy:

- Free IEX/website data may support lab and personal observation.
- It must not be described as professional realtime/NBBO/full-market data.
- A-share realtime core data requires licensed feed or explicit lab-only status.
- SEC/official filings can support free fundamental ingestion for US stocks, but
  point-in-time normalization remains non-trivial.

Acceptance:

- Provider status is visible in UI and API.
- Documentation clearly states coverage limits.

## P3: Versioned Equity Decision Engine

### P3.1 Implement V1 Scorer

Owner: Quant Research Lead

Use only measurable v1 features:

- trend: price versus MA200, 63-day return, 126-day return
- momentum: 20-day return excluding last 5 days
- risk: 20-day volatility, 63-day max drawdown, downside volatility
- liquidity: 20-day traded value
- event risk: earnings window, stale data, abnormal gap

Do not use valuation or fundamentals until point-in-time data exists.

Outputs:

- `model_version`
- `data_version`
- `as_of`
- feature values
- factor scores
- hard gates
- total score
- action band
- explanation
- invalidation conditions

Acceptance:

- Same snapshot + same model version produces identical output.
- Live analysis and backtest call the same scorer.

### P3.2 Replace Fixed Action Levels

Owner: Quant Research Lead + Portfolio Lead

Why:

- Current add/trim/risk-exit levels are fixed percentages from price.

New inputs:

- volatility
- MA/support bands
- recent drawdown
- liquidity
- target portfolio risk
- available cash

Acceptance:

- Action levels cannot exist without portfolio state and measured features.
- UI explains which constraints determine the level.

## P4: Backtest Protocol

### P4.1 Build Equity Backtest Harness

Owner: Quant Research Lead

Requirements:

- point-in-time universe
- adjusted OHLCV with corporate action metadata
- next-bar execution
- fees, spread, slippage, liquidity participation
- train/validation/test windows
- purge and embargo
- benchmark comparison
- stored run metadata

Acceptance:

- Every backtest result has a `run_id`.
- Historical run is reproducible from data version and model version.
- No test redefines production analyzers internally.

### P4.2 Add Bias Tests

Owner: Quant Research Lead

Tests:

- lookahead truncation invariance
- survivorship bias guard
- company action adjustment guard
- stale data guard
- parameter stability
- transaction cost sensitivity

Acceptance:

- Backtest cannot pass if future data affects a historical signal.

## P5: Portfolio, Paper Broker, and Risk

### P5.1 Implement Paper Broker

Owner: Portfolio and Platform Lead

States:

```text
created -> accepted -> working -> partially_filled -> filled
                                      -> cancelled
                                      -> rejected
                                      -> unknown
```

Rules:

- Submitted does not mean filled.
- Only fills change cash and positions.
- Every broker action has idempotency key and audit event.

Acceptance:

- Partial fill, cancel, reject, and unknown-order recovery are tested.

### P5.2 Build Ledger-Based Portfolio

Owner: Portfolio and Platform Lead

Objects:

- `CashLedger`
- `PositionLot`
- `PnLSnapshot`
- `ExposureSnapshot`

Acceptance:

- Portfolio can be rebuilt from fills and ledger entries.
- UI positions reconcile with ledger.

### P5.3 Replace RiskChecker

Owner: Portfolio and Platform Lead

Current risk checker only checks unsigned order size.

New checks:

- available cash
- signed exposure
- single-name exposure
- event/category exposure
- open order exposure
- residual leg exposure
- stale quote gate
- daily loss gate
- drawdown gate
- max slippage
- kill switch

Acceptance:

- Blocked actions report exact rule, input value, threshold, and remediation.

## P6: Review Loop

### P6.1 Add Review Journal

Owner: Product Lead

Objects:

- `ReviewRecord`
- `DecisionOutcome`
- `ExecutionOutcome`
- `Lesson`
- `RuleChange`

Metrics:

- thesis outcome
- probability calibration
- edge realization
- execution slippage
- PnL attribution
- model error versus operator override

Acceptance:

- Closed or invalidated cases generate review tasks.
- Review can distinguish research error, sizing error, execution error, and
  data error.

## P7: Reliability and Operations

### P7.1 Add Health and Readiness

Owner: Platform Lead

Endpoints:

- `/health/live`
- `/health/ready`
- `/metrics`

Checks:

- database
- data freshness
- provider status
- background jobs
- strategy loop status
- paper broker reconcile status

Acceptance:

- The system does not report ready if required data or DB is unavailable.

### P7.2 Fix Startup Supervision

Owner: Platform Lead

Scope:

- `start-all.sh`
- `start.sh`
- README startup instructions

Tasks:

- Avoid blind port killing unless PID ownership is known.
- Poll readiness instead of sleeping.
- Fail if any core child process exits.
- Do not build Next while dev server is running.

Acceptance:

- One command starts the system reliably.
- Stopping the command stops only owned child processes.

## Recommended Immediate Implementation Order

1. P0.1: Mark equity recommendations as lab/synthetic.
2. P0.2: Replace missing portfolio zeroes with unknown/not configured.
3. P0.3: Declare one API entrypoint and archive or disable the old one.
4. P1.1: Add local SQLite fact store and audit event table.
5. P1.2: Add investment case lifecycle APIs.
6. P5.1/P5.2: Add paper broker and ledger.
7. P1.3/P6.1: Convert homepage into work queue and add reviews.
8. P2.1/P2.2: Move equity data behind backend canonical data APIs.
9. P3.1/P4.1: Implement v1 scorer and backtest harness.

Do not expand stock coverage, add more indicators, or add new dashboards before
P0 and P1 are complete.
