# Project Memory TOC

This file is a navigation-only entrypoint for project memory. Do not store detailed instructions here.

Read the project memory files in this order:

1. `./.ai/memory/product-context.md`
2. `./.ai/memory/engineering-rules.md`
3. `./.ai/memory/validation-rules.md`
4. `./.ai/memory/ui-ux-rules.md`
5. `./.ai/memory/change-logics.md`

For non-trivial implementation or fixes, autonomously use PolyBob Development
Control: run `uv run --locked python scripts/dev_control.py board`, reuse or create one task, and track its
state. Skip read-only analysis and trivial one-line edits. Follow
`./.ai/workflows/workflows/development-control.md` and validate against
`./.ai/constraints/constraints/development-control-integrity.md`. Never automatically
commit or run `rollback --yes`; actual rollback requires explicit user approval.
Use Development Control `commit` and `push` only when the user asks for those Git actions.
For Git problems, run `doctor` first; never auto force-push, reset, or discard changes.
New branches must use neutral `pb-NNNN-short-title` names and must not contain
Codex, Claude, OpenAI, ChatGPT, or other agent/product branding. Use
`branch-plan --fetch` before branching and `promote` to verify whether work has
reached `main`.

Load `./.ai/memory/memory-write-audit.md` only when reviewing write history or migration records.

If the project also uses Claude Code, mirror the same TOC in `./CLAUDE.md`.
