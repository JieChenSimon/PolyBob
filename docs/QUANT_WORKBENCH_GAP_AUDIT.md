# PolyBob Quant Workbench Gap Audit

## Decision

PolyBob is a personal research workbench, not an institutional OMS/EMS. The
useful near-term target is therefore a trustworthy single-operator research
terminal: point-in-time evidence, explicit data quality, reproducible model
runs, durable operator choices, and a hard boundary between research and
execution.

This iteration deliberately does not claim to add institutional exchange
connectivity, distributed factor computation, tick replay, a production ledger,
or portfolio attribution. Those remain separate projects with different safety
and data requirements.

## Measured gaps

| Layer | Before this iteration | Risk | This iteration |
|---|---|---|---|
| Page role | Category and instrument routes both rendered full AAPL analysis | Two URLs and two interaction models for one decision | Category becomes a master/detail workbench; instrument route remains the focused deep link |
| First viewport | Duplicate titles and empty opportunity card preceded the chart | Current price, freshness and model control were buried | Compact route header; wider analysis surface; evidence details collapsed by default |
| Responsive UX | Mobile list followed thousands of pixels of detail | Switching instruments required excessive scrolling | Explicit `detail / watchlist` segmented control |
| Forecast control | One process-wide environment switch | A button could not authorize one symbol without authorizing all symbols | Durable per-domain/per-symbol opt-in in SQLite |
| API semantics | Expensive inference was triggered by `GET` | GET retries, prefetch and caches could start computation | New work uses `POST /api/forecasting/runs`; GET remains compatibility-only |
| Safety | Forecast endpoint checked only the process-wide switch | Any supported symbol could run once the engine was on | Engine readiness **and** instrument allowlist are both required, fail-closed |
| Auditability | Operator enable/disable choices were ephemeral | Restarts lost intent and there was no trace | Every state change is persisted and appended to `audit_events` |
| Data trust | Status/source repeated across unrelated cards | Contradictory `connected / not configured` labels | Source, timestamp and portfolio boundary are consolidated |
| Forecast interpretation | A percentile table implied precision without explaining evidence quality | Three paths looked like a calibrated probability and model output looked causal | Historical/forecast fan chart, unchanged-price baseline, input-state descriptors, confidence defects and interval-breach rule are shown together |

## Forecast explanation contract

The workbench separates three claims that must not be conflated:

1. **Model output**: P10/P50/P90 and terminal median return describe the sampled
   Kronos distribution.
2. **Observed input state**: recent return, realised volatility, drawdown and
   volume ratio are deterministic descriptions of the bars supplied to the
   model. They are not feature importance or causal attribution.
3. **Trust state**: path count, calibration, exchange-calendar quality and
   walk-forward availability determine whether the output is statistically
   reviewable. Missing walk-forward evidence remains `UNKNOWN`.

When fewer than 100 paths are sampled, the UI reports an integer such as
`0/3 up paths`, not a probability claim. Any realised close outside the
corresponding P10-P90 band is recorded as an interval breach; it is not called
proof of model causality or failure of a particular feature.

## Resulting state machine

```text
ENGINE OFF
  └─ no instrument can be enabled or run

ENGINE READY + INSTRUMENT OFF
  └─ operator may explicitly enable exactly one domain:symbol

ENGINE READY + INSTRUMENT READY
  ├─ operator may choose 1/5/10/20 day horizon
  ├─ POST creates an on-demand research run
  └─ operator may disable the instrument at any time

RUN COMPLETE
  └─ result records model revision, source, as-of, calibration and gate reason;
     trade permission remains denied unless the independent promotion gate and
     calibration requirements both pass
```

## Remaining distance to an institutional quant platform

1. Durable forecast-run registry with input data hashes, latency, error history
   and artifact retention.
2. Point-in-time corporate-action policy for US and A-share model inputs.
3. Walk-forward model monitoring against naive baselines, with decay alarms.
4. Portfolio ledger, factor/risk attribution and scenario stress testing.
5. Deterministic event replay and realistic fill/cost models.
6. Background run queue, cancellation and compute-resource admission control.
7. Authentication and authorization if the workbench ever stops being strictly
   single-operator/local.

None of those may be represented in the UI as configured before the underlying
data, persistence and validation paths exist.
