# Task System Integrity

## Scope

适用于 `tasks/items/*.yml`、任务 CLI、任务相关分支和提交。

## Hard Acceptance Criteria

- 任务 ID 必须唯一且符合 `PB-NNNN`。
- 状态和优先级必须来自仓库定义的枚举。
- 每个任务只保留决策所需字段，并包含 title、why、area 和至少一条可验证 check。
- 依赖必须存在、不能自依赖、任务图不能成环。
- `doing` 数量不能超过配置的 WIP limit。
- `blocked` 必须记录原因和时间。
- `done` 必须勾选全部 check、完成全部依赖，并有带任务 trailer 的真实提交。
- `codex/pb-NNNN-*` 分支上的普通提交必须带 `PolyBob-Task: PB-NNNN` trailer。
- `stop` 必须记录原因，且不得修改工作代码。
- `rollback` 必须先预览；实际执行需显式确认、干净工作区，并只能 revert 该任务关联的
  非 merge commit。禁止用 reset 或覆盖未提交内容。
- `commit` 只能暂存明确路径；暂存区非空时拒绝，提交必须自动写任务 trailer。
- `push` 必须验证当前任务分支、关联提交和 remote；禁止隐式 force-push。
- Git 修复先诊断；自动修复仅限可逆的本地配置/元数据。终止 merge/rebase/cherry-pick/
  revert 必须显式确认；冲突、分叉和 detached HEAD 不得猜测处理。

## Rejection Conditions

任何悬空依赖、非法迁移、伪造 commit、未验收完成、无原因阻塞或超 WIP 均拒绝。

## Validation

运行 `python scripts/task_tracker.py validate`；CI 中该命令必须通过。
