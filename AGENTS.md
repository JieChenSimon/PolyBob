# Project Memory TOC

This file is a navigation-only entrypoint for project memory. Do not store detailed instructions here.

Read the project memory files in this order:

1. `./.ai/memory/product-context.md`
2. `./.ai/memory/engineering-rules.md`
3. `./.ai/memory/validation-rules.md`
4. `./.ai/memory/ui-ux-rules.md`
5. `./.ai/memory/change-logics.md`

For non-trivial implementation or fixes, autonomously use the task system: run
`python scripts/task_tracker.py board`, reuse or create one task, and track its
state. Skip read-only analysis and trivial one-line edits. Follow
`./.ai/workflows/workflows/task-lifecycle.md` and validate against
`./.ai/constraints/constraints/task-system-integrity.md`. Never automatically
commit or run `rollback --yes`; actual rollback requires explicit user approval.
Use task-system `commit` and `push` only when the user asks for those Git actions.
For Git problems, run `doctor` first; never auto force-push, reset, or discard changes.

Load `./.ai/memory/memory-write-audit.md` only when reviewing write history or migration records.

If the project also uses Claude Code, mirror the same TOC in `./CLAUDE.md`.
