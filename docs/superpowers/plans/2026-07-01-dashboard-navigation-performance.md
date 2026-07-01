# Dashboard Navigation Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PolyBob route shells immediate while preserving truthful realtime data, existing controls, and all financial calculations.

**Architecture:** Replace route-blocking server fetches and component-local polling state with a root-scoped TanStack Query cache. Keep provider calls asynchronous behind stable route shells, and bound expensive discovery-table rendering with tested pagination and deferred filtering.

**Tech Stack:** Next.js 15 App Router, React 19, TypeScript, TanStack Query, Vitest, FastAPI/pytest.

---

### Task 1: Query Runtime Foundation

**Files:**
- Modify: `apps/dashboard/package.json`
- Modify: `apps/dashboard/package-lock.json`
- Create: `apps/dashboard/lib/queryClient.tsx`
- Create: `apps/dashboard/lib/queryClient.test.ts`
- Modify: `apps/dashboard/app/layout.tsx`

- [ ] **Step 1: Write failing tests for shared query defaults**

Test that the workbench query client disables background polling, uses bounded cache retention, and does not retry requests indefinitely.

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `cd apps/dashboard && npm test -- lib/queryClient.test.ts`

- [ ] **Step 3: Install TanStack Query and implement the root provider**

Create one browser-stable `QueryClient`, expose tested default options, and wrap the dashboard body with `WorkbenchQueryProvider`.

- [ ] **Step 4: Run the focused test and confirm GREEN**

Run: `cd apps/dashboard && npm test -- lib/queryClient.test.ts`

### Task 2: Non-blocking Polymarket Route

**Files:**
- Create: `apps/dashboard/app/polymarket/page.test.ts`
- Modify: `apps/dashboard/app/polymarket/page.tsx`
- Modify: `apps/dashboard/components/BtcFiveMinuteWorkbenchClient.tsx`
- Create: `apps/dashboard/app/polymarket/loading.tsx`

- [ ] **Step 1: Write a failing test proving the page returns synchronously**

Import the page component, invoke it, and assert it does not return a Promise and does not call `fetch`.

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `cd apps/dashboard && npm test -- app/polymarket/page.test.ts`

- [ ] **Step 3: Move workbench loading into `useQuery`**

Use key `['polymarket', 'btc-5m', 'workbench']`, 3-second active polling, a 2-second stale time, request cancellation, and the existing unavailable/no-trade parser behavior.

- [ ] **Step 4: Add a stable route loading shell**

Match the page width and terminal panel geometry so navigation feedback is immediate and layout shift is bounded.

- [ ] **Step 5: Run focused tests and confirm GREEN**

Run: `cd apps/dashboard && npm test -- app/polymarket/page.test.ts domain/btcFiveMinute/workbench.test.ts`

### Task 3: Non-blocking And Bounded Altcoin Discovery

**Files:**
- Create: `apps/dashboard/app/crypto/altcoin-discovery/page.test.ts`
- Modify: `apps/dashboard/app/crypto/altcoin-discovery/page.tsx`
- Modify: `apps/dashboard/components/AltcoinDiscoveryWorkspace.tsx`
- Modify: `apps/dashboard/domain/altcoinDiscovery/workbench.ts`
- Modify: `apps/dashboard/domain/altcoinDiscovery/workbench.test.ts`
- Create: `apps/dashboard/app/crypto/altcoin-discovery/loading.tsx`

- [ ] **Step 1: Write failing route and pagination tests**

Assert the route is synchronous and fetch-free. Assert pagination returns no more than 30 candidates, clamps invalid pages, and reports total pages.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `cd apps/dashboard && npm test -- app/crypto/altcoin-discovery/page.test.ts domain/altcoinDiscovery/workbench.test.ts`

- [ ] **Step 3: Move list and detail reads to TanStack Query**

Keep the last successful list snapshot, use a 10-second active polling interval, disable background polling, and retain existing source-health and refresh-error UI.

- [ ] **Step 4: Add deferred filtering and 30-row pagination**

Filter the full candidate set using the deferred query, reset pagination after filter/sort changes, and preserve selected-candidate behavior.

- [ ] **Step 5: Add a stable terminal loading shell and confirm GREEN**

Run: `cd apps/dashboard && npm test -- app/crypto/altcoin-discovery/page.test.ts domain/altcoinDiscovery/workbench.test.ts`

### Task 4: Shared Cache For Remaining Polling Workspaces

**Files:**
- Modify: `apps/dashboard/components/OverviewWorkspace.tsx`
- Modify: `apps/dashboard/components/MarketsWorkspace.tsx`
- Modify: `apps/dashboard/components/RiskOpsOverview.tsx`
- Modify: `apps/dashboard/components/ExecutionWorkspace.tsx`
- Modify: `apps/dashboard/components/StrategyCatalog.tsx`

- [ ] **Step 1: Preserve current parsing and error contracts in focused query functions**

Use stable query keys and current refresh intervals; pass `AbortSignal` through every GET request.

- [ ] **Step 2: Replace local mount-time polling with `useQuery`**

Keep mutation handlers intact and invalidate/refetch only the affected query after successful mutations.

- [ ] **Step 3: Verify no inactive workspace produces polling traffic**

Navigate away in the production browser and inspect API logs for the previous route's query endpoints.

### Task 5: Regression And Performance Verification

**Files:**
- Modify: `docs/performance-benchmarks.md`

- [ ] **Step 1: Run frontend tests**

Run: `cd apps/dashboard && npm test`

- [ ] **Step 2: Run backend tests**

Run: `conda run -n polybob python -m pytest -q`

- [ ] **Step 3: Build production dashboard**

Run: `cd apps/dashboard && npm run build`

- [ ] **Step 4: Run production route and API timing checks**

Confirm `/polymarket` and `/crypto/altcoin-discovery` route TTFB no longer tracks provider latency and record response sizes.

- [ ] **Step 5: Browser smoke test all routes**

Verify Chinese and English navigation, data refresh, filters, selection, actions, console errors, horizontal overflow, and truthful stale/unavailable states.

- [ ] **Step 6: Record before/after evidence**

Update `docs/performance-benchmarks.md` with exact commands, route timings, payload sizes, test counts, and any remaining bottlenecks.

