# BTC 5m Entry Optimizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explainable BTC five-minute entry optimizer that returns a core conclusion, price zones, and full execution suggestions.

**Architecture:** Extend the existing `libs/polymarket/btc_five_minute.py` domain layer so API consumers receive optimizer fields in the existing workbench payload. Keep frontend changes to parsing and display only.

**Tech Stack:** Python domain logic and pytest; Next.js/TypeScript dashboard with Vitest.

---

### Task 1: Backend Entry Optimizer

**Files:**
- Modify: `libs/polymarket/btc_five_minute.py`
- Test: `tests/unit/test_btc_five_minute_workbench.py`

- [ ] **Step 1: Write failing tests**

Add tests for missing target price, favorable UP entry, high ask avoidance, Kelly cap, and price band consistency.

- [ ] **Step 2: Run tests to verify failure**

Run: `conda run -n polybob python -m pytest -q tests/unit/test_btc_five_minute_workbench.py`

- [ ] **Step 3: Implement minimal domain logic**

Add `entry_analysis` to each outcome and `entry_optimizer` to the workbench payload. The calculation must use target price, BTC reference price, order-book midpoints, EV, and fractional Kelly.

- [ ] **Step 4: Run backend tests**

Run: `conda run -n polybob python -m pytest -q tests/unit/test_btc_five_minute_workbench.py`

### Task 2: API Contract Tests

**Files:**
- Modify: `tests/test_api_btc_five_minute_workbench.py`

- [ ] **Step 1: Add contract assertion**

Extend the endpoint payload test to assert `entry_optimizer` and per-outcome `entry_analysis`.

- [ ] **Step 2: Run API tests**

Run: `conda run -n polybob python -m pytest -q tests/test_api_btc_five_minute_workbench.py`

### Task 3: Dashboard Parsing and Display

**Files:**
- Modify: `apps/dashboard/domain/btcFiveMinute/workbench.ts`
- Modify: `apps/dashboard/domain/btcFiveMinute/workbench.test.ts`
- Modify: `apps/dashboard/components/BtcFiveMinuteMarketTerminal.tsx`
- Modify: `apps/dashboard/components/BtcFiveMinuteWorkspace.tsx`

- [ ] **Step 1: Write failing parser test**

Add expected `entry_optimizer` and `entry_analysis` values to the existing parser test.

- [ ] **Step 2: Run dashboard tests to verify failure**

Run: `npm run test` in `apps/dashboard`.

- [ ] **Step 3: Add TypeScript types and parser logic**

Parse the optimizer payload without throwing when older payloads omit it.

- [ ] **Step 4: Display optimizer outputs**

Show core entry conclusion in the terminal and price zones / Kelly / EV in detail panels.

- [ ] **Step 5: Run dashboard tests and build**

Run: `npm run test` and `npm run build` in `apps/dashboard`.

### Task 4: Full Verification

**Files:**
- No new files.

- [ ] **Step 1: Run full Python tests**

Run: `conda run -n polybob python -m pytest -q`

- [ ] **Step 2: Run dashboard build**

Run: `rm -rf .next && npm run build` in `apps/dashboard`.

- [ ] **Step 3: Real API smoke test**

Start API/dashboard if needed and verify `/api/polymarket/btc-5m/workbench` returns real `target_price`, `entry_optimizer`, and no fabricated order book.
