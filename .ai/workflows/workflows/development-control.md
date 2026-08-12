# Development Control Workflow

## Trigger

Codex 对 PolyBob 进行非微小开发时自主使用。满足任一条件即触发：改变运行行为、数据或
接口；涉及多个文件/步骤；需要测试、回滚或后续追踪；用户明确要求实现或修复。

只读分析、单处文案/拼写修正、不会保留的诊断操作不建任务。用户明确说不追踪时不触发。

## Procedure

1. 先运行 `uv run --locked python scripts/dev_control.py board`，避免重复任务。
2. 新工作用 `new` 建立任务，只写原因、area、priority 和可验证 check。
3. 实现前用 `move <id> doing` 或 `branch <id>` 开始。
   新分支先运行 `branch-plan --fetch`，复用已有任务分支或从远端 `main` 创建。
4. 提交信息加入 `PolyBob-Task: PB-NNNN`；Git 历史就是提交事实源。
5. 阻塞用 `move <id> blocked --reason ...`；解除用 `move <id> doing`。
6. 验证后逐项 `check`，最后用 `move <id> done` 关闭。
7. 结束前运行 `uv run --locked python scripts/dev_control.py validate`。
8. 用户终止工作时用 `stop --reason`；它只终止任务，不回滚代码。
9. 只有用户明确要求回滚时才运行 `rollback`；先预览，获得确认后才加 `--yes`。
10. 用户要求提交或推送时，用任务系统的 `commit` / `push`；先用 `doctor` 检查 Git。
11. Git 异常先运行 `doctor`。只有安全配置可用 `--fix`；未结束操作经用户确认后才
    `git-abort --yes`，冲突内容由 Codex逐文件分析解决。
12. 推送任务分支后检查目标分支。若用户要求进入 `main`，先运行 `promote` 预览；仅当
    fast-forward 且用户明确确认时运行 `promote --yes`。

## Forbidden Actions

- 不绕过状态机直接把任务 YAML 改成 `done`。
- 不以模糊描述代替 acceptance criterion。
- 不把 UNKNOWN、未运行或未检查写成已完成。
- 不手工创建汇总看板作为第二事实源。
- 不因自动触发而自动提交、回滚或丢弃用户改动。
- 不自动 force-push、reset、清理未跟踪文件或替用户选择冲突内容。
- 新建分支不得包含 Codex、Claude、OpenAI、ChatGPT 或其他代理/产品标识。

## Quality Gate

开发控制图校验必须通过；完成任务必须有全部 check、已完成依赖和带 trailer 的真实提交。
