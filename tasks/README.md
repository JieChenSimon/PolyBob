# Tasks

每项任务一个短 YAML；Git 保存历史，CLI 保证状态准确。

```bash
python scripts/task_tracker.py board                 # 总览
python scripts/task_tracker.py show PB-0001          # 详情 + Git
python scripts/task_tracker.py new "标题" -a api -p P1 \
  --why "要解决的问题" --check "可验证结果"
python scripts/task_tracker.py move PB-0001 doing
python scripts/task_tracker.py check PB-0001 1
python scripts/task_tracker.py move PB-0001 done      # 验收、依赖、提交均通过才允许
python scripts/task_tracker.py stop PB-0001 --reason "不再需要"  # 终止追踪，不改代码
python scripts/task_tracker.py rollback PB-0001       # 只预览关联提交
python scripts/task_tracker.py rollback PB-0001 --yes # 安全生成 git revert commit
python scripts/task_tracker.py commit PB-0001 -m "修复打包" --path pyproject.toml
python scripts/task_tracker.py push PB-0001            # push 并自动设置 upstream
python scripts/task_tracker.py doctor                  # Git 健康诊断
python scripts/task_tracker.py doctor --fetch          # 刷新远端后准确判断分叉
python scripts/task_tracker.py doctor --fix            # 只修安全的本地配置
python scripts/task_tracker.py git-abort --yes          # 终止卡住的 Git 操作
python scripts/task_tracker.py validate
```

任务分支使用 `codex/pb-0001-title`。提交信息加：

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
