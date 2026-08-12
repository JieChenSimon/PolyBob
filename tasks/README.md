# PolyBob Development Control

开发控制系统统一管理任务、Git、分支、发布、诊断、终止、恢复和回滚。每项任务仍是一个
短 YAML；Git 保存历史，CLI 保证状态准确。

```bash
uv run --locked python scripts/dev_control.py board                 # 总览
uv run --locked python scripts/dev_control.py show PB-0001          # 详情 + Git
uv run --locked python scripts/dev_control.py new "标题" -a api -p P1 \
  --why "要解决的问题" --check "可验证结果"
uv run --locked python scripts/dev_control.py move PB-0001 doing
uv run --locked python scripts/dev_control.py check PB-0001 1
uv run --locked python scripts/dev_control.py move PB-0001 done      # 验收、依赖、提交均通过才允许
uv run --locked python scripts/dev_control.py stop PB-0001 --reason "不再需要"  # 终止追踪，不改代码
uv run --locked python scripts/dev_control.py rollback PB-0001       # 只预览关联提交
uv run --locked python scripts/dev_control.py rollback PB-0001 --yes # 安全生成 git revert commit
uv run --locked python scripts/dev_control.py commit PB-0001 -m "修复打包" --path pyproject.toml
uv run --locked python scripts/dev_control.py push PB-0001            # push 并自动设置 upstream
uv run --locked python scripts/dev_control.py branch-plan PB-0001 --fetch # 只读分支决策
uv run --locked python scripts/dev_control.py branch PB-0001           # 从远端 main 新建/复用任务分支
uv run --locked python scripts/dev_control.py promote PB-0001 --to main # 预览发布到 main
uv run --locked python scripts/dev_control.py promote PB-0001 --to main --yes # 仅 fast-forward 发布
uv run --locked python scripts/dev_control.py doctor                  # Git 健康诊断
uv run --locked python scripts/dev_control.py doctor --fetch          # 刷新远端后准确判断分叉
uv run --locked python scripts/dev_control.py doctor --fix            # 只修安全的本地配置
uv run --locked python scripts/dev_control.py git-abort --yes          # 终止卡住的 Git 操作
uv run --locked python scripts/dev_control.py validate
```

新任务分支使用 `pb-0001-title`，不包含 Codex、Claude、OpenAI、ChatGPT 等代理或产品名。
提交信息加：

```text
PolyBob-Task: PB-0001
```

启用仓库 hook：`git config core.hooksPath .githooks`。

状态只有五个：`todo → doing ↔ blocked → done`；放弃用 `dropped`。WIP 上限见
`tasks/config.yml`。不要维护第二份汇总文件，`board` 始终从任务事实源即时生成。

`rollback` 只处理带本任务 trailer 的提交；工作区不干净、提交不在当前分支或包含 merge
commit 时拒绝执行。它不会使用 `reset --hard`，因此回滚本身仍可审查、可再次恢复。

`commit` 只暂存明确给出的 `--path` 和任务文件，若暂存区原本有内容则拒绝，防止混入别人的
改动。`doctor` 检查 detached HEAD、冲突、未结束操作、上下游分叉、hook 和任务分支；
不能安全自动解决的问题只给出结论，不擅自 reset、force-push 或覆盖文件。

分支决策遵循：已有任务分支就复用；否则从最新远端 `main` 建立中性命名分支；脏工作区、
错任务分支或分叉时停止。`push` 发布任务分支，`promote` 才把当前分支推进目标分支；默认
只预览，且目标不是当前分支祖先时拒绝，避免再次出现“功能分支有、main 没有”的盲区。
