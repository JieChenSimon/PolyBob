# Extensible Research Knowledge Base Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an extensible local research knowledge base with a StatementDog ingestion source and dashboard access.

**Architecture:** Create provider-neutral Python contracts under `libs/knowledge`, store normalized documents in SQLite with FTS5 fallback, run ingestion in a background service, expose FastAPI endpoints, and add a `/research` dashboard route. StatementDog is one adapter and is gated by explicit authorization config.

**Tech Stack:** Python 3.11, FastAPI, httpx, SQLite/FTS5, standard-library HTML parsing, Next.js dashboard, TanStack Query.

---

### Task 1: Storage And Search

**Files:**
- Create: `libs/knowledge/models.py`
- Create: `libs/knowledge/store.py`
- Create: `libs/knowledge/__init__.py`
- Test: `tests/test_knowledge_store.py`

- [ ] Write failing tests for idempotent schema creation, upsert, recent documents, FTS search, and fallback search.
- [ ] Run `conda run -n polybob python -m pytest tests/test_knowledge_store.py -q` and confirm failure.
- [ ] Implement `KnowledgeDocument`, `KnowledgeSearchResult`, `SourceRunStatus`, and `KnowledgeStore`.
- [ ] Run the targeted test and confirm pass.

### Task 2: StatementDog Parsing And Source

**Files:**
- Create: `libs/knowledge/sources/base.py`
- Create: `libs/knowledge/sources/statementdog.py`
- Create: `libs/knowledge/sources/__init__.py`
- Test: `tests/test_statementdog_source.py`

- [ ] Write failing tests for sitemap discovery, lookback filtering, JSON-LD/article parsing, ticker parsing, and authorization-disabled behavior.
- [ ] Run `conda run -n polybob python -m pytest tests/test_statementdog_source.py -q` and confirm failure.
- [ ] Implement provider-neutral source protocol and StatementDog source.
- [ ] Run the targeted test and confirm pass.

### Task 3: Background Service And API

**Files:**
- Create: `modules/knowledge_ingestion/service.py`
- Create: `modules/knowledge_ingestion/__init__.py`
- Modify: `libs/config.py`
- Modify: `apps/api/main.py`
- Test: `tests/test_knowledge_ingestion_service.py`
- Test: `tests/test_api_knowledge.py`

- [ ] Write failing tests for disabled default startup, manual refresh, source status, search API, recent API, and refresh error payloads.
- [ ] Run targeted tests and confirm failure.
- [ ] Implement service lifecycle, config fields, global service wiring, and API endpoints.
- [ ] Run targeted tests and confirm pass.

### Task 4: Dashboard Route

**Files:**
- Create: `apps/dashboard/domain/research/knowledge.ts`
- Create: `apps/dashboard/domain/research/knowledge.test.ts`
- Create: `apps/dashboard/components/ResearchWorkspace.tsx`
- Create: `apps/dashboard/app/research/page.tsx`
- Create: `apps/dashboard/app/research/page.test.ts`
- Modify: `apps/dashboard/components/PrimaryNav.tsx`
- Modify: `apps/dashboard/lib/types.ts`

- [ ] Write failing dashboard tests for payload parsing and route/static/nav contract.
- [ ] Run `cd apps/dashboard && npm test -- domain/research/knowledge.test.ts app/research/page.test.ts components/PrimaryNav.test.ts`.
- [ ] Implement parser, page shell, workspace, nav item, and types.
- [ ] Run targeted dashboard tests and confirm pass.

### Task 5: Verification

**Files:**
- Modify docs if command output reveals operational instructions that need clarification.

- [ ] Run `conda run -n polybob python -m pytest tests/test_knowledge_store.py tests/test_statementdog_source.py tests/test_knowledge_ingestion_service.py tests/test_api_knowledge.py -q`.
- [ ] Run `conda run -n polybob python -m pytest -q`.
- [ ] Run `cd apps/dashboard && npm test`.
- [ ] Run `cd apps/dashboard && npm run build`.
- [ ] Run `git diff --check`.
