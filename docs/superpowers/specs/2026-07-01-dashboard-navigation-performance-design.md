# Dashboard Navigation Performance Design

## Goal

Make PolyBob route changes feel immediate without weakening realtime data freshness, source transparency, failure handling, or existing workflows.

## Measured Baseline

- Static top-level routes return their HTML locally in roughly 1-2 ms, so their remaining interaction delay is client-side loading, mounting, data fetching, and rendering work.
- `/polymarket` blocks route rendering on `/api/polymarket/btc-5m/workbench`; measured API time-to-first-byte was 7.73 seconds and page time-to-first-byte was 4.28 seconds in the sampled run.
- `/crypto/altcoin-discovery` serializes the complete discovery payload into the route response. The sampled response was approximately 261 KB and rendered 126 table rows.
- `/polymarket` and `/crypto/altcoin-discovery` fetch on the server and then immediately fetch again when client polling mounts.
- First-load JavaScript is approximately 214 KB for Markets and 226 KB for Equities because charting code is included in those route bundles.

## Architecture

### 1. Non-blocking route shells

Top-level pages must render their navigation, title, primary controls, and stable loading state without waiting for market-data providers. Realtime workbench requests move to client-side query hooks. Slow or unavailable providers may delay data, but never route commitment.

Dynamic route-level fetches using `force-dynamic` and `no-store` are removed from Polymarket and Altcoin Discovery. Route loading boundaries provide an immediate, dimensionally stable fallback for any remaining server work.

### 2. Shared client query cache

Use TanStack Query as the shared server-state layer. A single `QueryClient` lives under the root layout and survives route changes.

Query policy:

- retain the last successful result across route changes;
- deduplicate identical in-flight requests;
- pass `AbortSignal` to fetch so obsolete requests can be cancelled;
- poll only while a query has an active observer;
- do not poll in a hidden browser tab;
- show cached data immediately on revisit, then refresh in the background;
- preserve existing source, observed-at, stale, delayed, unavailable, and no-trade semantics;
- never manufacture placeholder prices, order books, scores, or recommendations.

Suggested freshness policy:

| Surface | Refetch interval | Stale time | Cache retention |
| --- | ---: | ---: | ---: |
| BTC 5-minute workbench | 3 s | 2 s | 5 min |
| Altcoin discovery list | 10 s | 8 s | 10 min |
| Daily brief / markets / risk / execution | existing interval | one interval | 5 min |
| Static settings/catalog metadata | manual or 60 s | 60 s | 15 min |

Mutation flows continue to invalidate or explicitly refetch their affected query keys after success.

### 3. Render-cost controls

- Render only a bounded window of discovery rows at once while filtering and sorting continue to operate over the complete candidate set.
- Use deferred search input for expensive candidate filtering.
- Memoize expensive row and chart subtrees only where measured props are stable.
- Load chart-heavy client components through route-local dynamic imports with stable skeleton dimensions.
- Keep current selected-item behavior, filters, bilingual labels, source health, and detail requests intact.

Pagination is preferred over a new virtualization dependency for the first pass because the current discovery set is hundreds, not tens of thousands, and deterministic pagination is easier to test and more accessible. Page size defaults to 30 and resets when filters change.

### 4. Navigation feedback

Navigation remains interruptible. Stable route skeletons use the same terminal/workbench geometry as the destination page to avoid layout shift. The active navigation item must update as soon as the destination route commits.

## Data And Error Flow

1. Route shell commits without provider data.
2. Query cache returns a valid prior snapshot when available.
3. Query function requests the current API payload with cancellation support.
4. Successful data replaces the cache and updates freshness labels.
5. A refresh failure retains the last successful snapshot and exposes the existing failure diagnosis.
6. If no successful snapshot exists, the page renders its explicit unavailable/no-trade state.

The API remains the authority for provider diagnostics and financial calculations. The frontend cache only coordinates transport and display lifecycle.

## Compatibility Boundaries

- No API schema or scoring logic changes are required.
- Existing polling frequencies remain unchanged unless the current implementation fires duplicate requests.
- Existing language switching, symbol selection, favorites, chart modes, strategy mutations, execution actions, and error messages remain functional.
- Real market data must never be replaced by fixtures outside automated tests.
- User-confirmed page content and financial conclusions are not redesigned as part of this performance work.

## Testing

### Automated behavior

- Query functions parse and preserve current payload semantics.
- Cached data survives unmount/remount and triggers one background refresh.
- Concurrent consumers produce one network request per query key.
- Aborted requests do not overwrite current state.
- Polling stops when a surface is inactive or the document is hidden.
- Discovery pagination renders at most 30 rows, filters the full dataset, and resets to the first page after filter changes.
- Route pages render a stable shell without awaiting provider data.

### Regression

- `conda run -n polybob python -m pytest -q`
- `cd apps/dashboard && npm test`
- `cd apps/dashboard && npm run build`
- Smoke test `/overview`, `/markets`, `/polymarket`, `/crypto/altcoin-discovery`, `/us-equities`, `/strategies`, `/execution`, `/risk-ops`, and `/settings` in Chinese and English.
- Verify no console errors, no horizontal overflow, and no stale snapshot presented as realtime.

### Performance acceptance

Run against the production build on the local machine:

- warm route-shell navigation p95 is at most 300 ms;
- no top-level route waits for an external provider before committing;
- revisiting a previously loaded route shows cached content without a blank state;
- one active request exists per query key;
- inactive routes produce no polling traffic;
- Altcoin Discovery initially renders at most 30 candidate rows;
- failure of Polymarket Gamma/CLOB does not delay navigation and still results in a truthful no-trade state.

## Rollout

1. Add the query provider and reusable query policies behind focused tests.
2. Convert Polymarket and Altcoin Discovery first because they have measured blocking and payload problems.
3. Convert remaining polling surfaces without changing their visible contracts.
4. Defer chart bundles and bound expensive lists.
5. Run full regression and production browser benchmarks, then compare against the recorded baseline.

