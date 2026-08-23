# PolyBob Capability Boundaries

PolyBob is a personal market research workbench with an experimental paper-execution
tail. It is not a production trading system. The runtime inventory is available at
`GET /api/capabilities`; this document explains the meaning of its labels.

| Tier | Promise |
| --- | --- |
| Core | A supported operator workflow. Its data may still be delayed, degraded, or unknown, and the UI must say so. |
| Lab | An opt-in experiment isolated from trading permission. Results require historical validation before promotion. |
| Archive | Retained reference code or a legacy prototype. It is not part of the supported workflow and is disabled. |

## Current Matrix

| Capability | Tier | Truthful operating boundary |
| --- | --- | --- |
| Market and instrument observation | Core | Research and observation only; every surface must expose provider and freshness. |
| Research evidence and promotion | Core | Promotion is fail-closed. The current board has no trade-approved edge. |
| Manual journal | Core / degraded | A manual research record, not the authoritative execution ledger. |
| Portfolio and risk state | Core / unknown | Unknown until a configured account and canonical fill projection exist. |
| Kronos forecasting | Lab | Per-instrument opt-in experiment; no trade permission and no rolling calibration yet. |
| Development control and settings | Core | Git-backed task truth plus read-only runtime capability status. |
| Paper execution | Lab / blocked | Prototype APIs exist, but the order-to-fill-to-ledger reconciliation chain is incomplete. |
| Strategy runtime | Lab / blocked | Research templates and stopped instances; no promoted trading runtime exists. |
| Research simulation | Lab | A research comparator, not execution-grade paper trading. |
| Automatic trader | Archive | Legacy prototype, disabled and absent from core navigation. |

## Non-negotiable Display Rules

1. `unknown` is never rendered as zero.
2. `disabled`, `degraded`, and `blocked` are not rendered as ready.
3. Lab output never grants trade permission.
4. An API's existence is not evidence that a capability is Core or production-ready.
5. New pages and APIs must be added to the runtime inventory before they can be described as supported.
