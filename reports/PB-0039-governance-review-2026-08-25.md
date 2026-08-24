# PB-0039 治理复核记录

复核日期：2026-08-25（Asia/Singapore）  
角色：治理产品负责人  
结论：**DOING，0/3；不得完成，不得交易晋级**

## 当前真实状态

- 任务文件 `tasks/items/PB-0039.yml` 仍为 `state=doing`，三个 check 均为 `done=false`。
- 当前分支为 `pb-0037-funding-strategy-replay`。最新相关提交 `12556c1`、`e0bf342`、`336740d`、`5eb1e26`、`329711a` 均带有 `PolyBob-Task: PB-0039`；共享 PB-0037 分支的归属和 reviewer 交接仍需单独记录。
- 最新错价产物显示 `3445` 个 settled windows、`2431` 个 qualifying trades、`13` 个独立聚类，`collection_status=complete`，但统计结果仍为 `status=unknown`、`resolvable=false`，且独立聚类低于 20。
- 最新 manifest 的代码状态为 `dirty=true`，`dirty_files=1`；`lineage.has_lineage=false`，`reproducible=false`。因此该快照不能作为可复现验收证据。
- calibration、direction replay、event replay 的 manifest 文件虽然存在，但关键字段 `experiment`、`as_of`、`inputs`、`lineage` 为空，仍未形成完整报告 lineage。
- 最新事件回放仍是 `diagnostic_not_promotion`、`tradable_evidence=false`；只有 1 个完整月份，收益目标必须继续为 `UNKNOWN`。
- Promotion Board 仍停留在旧快照 `n=2360`、`n_clusters=12`，而当前证据为 `n=2431`、`n_clusters=13`；`event_study_board.py --check` 已报告 `data/promotion_board.json 与证据不一致`。因此 Board 当前不能作为最新验收快照。
- 定向测试本轮为 `13 passed`，`dev_control validate` 通过；这不等同于完整测试套件、lineage 复现和 Promotion Board 重建全部完成。

## 本轮验收判定

| 验收项 | 当前判定 | 原因 |
|---|---|---|
| 真实数据至少 20 个独立交易日 | 未完成 | 任务 check 未勾选；13 个统计独立聚类不能替代真实覆盖/PIT 验收 |
| 时间切分、逐日/逐月收益、回撤审计 | 未完成 | 只有 1 个完整月份，且跨报告快照/manifest 尚未闭环 |
| 年化 50% 且每完整月 15% | UNKNOWN | 仅 1 个完整月份；收益目标门禁要求 12 个月 |
| Promotion Board 交易晋级 | 拒绝 | Board 已过期且当前证据仍有 dirty、lineage false、clusters<20、PIT 不可交易 |

## 下一轮必须补齐

1. 停止或隔离并发证据生成，固定一个干净 Git commit 和统一 `as_of`，再生成全套报告。
2. 为 calibration、direction replay、event replay 补齐完整 manifest，并校验报告 hash、输入 hash、PIT、参数、覆盖范围和代码 dirty 状态。
3. 统一 settled 数据的真实独立交易日、独立月份和聚类口径；在独立聚类达到 20 前，保持 `UNKNOWN` 和禁止交易晋级。
4. 重新执行时间切分、逐日/逐月收益、回撤、成本压力和未平仓审计；不足 12 个完整月份时不得勾选收益目标 check。
5. 在干净快照上重建 Promotion Board，使 Board 的 `n`、`n_clusters`、`run_as_of`、manifest 和失败原因与报告一致；当前 `approved_trade` 必须保持 0。
6. 补充 PB-0039 专属数据、量化、执行和治理 reviewer 交接记录，并明确 PB-0037/PB-0039 的共享分支验收归属。
7. 完成完整测试套件、lineage/manifest 测试、Board 重建检查和真实数据复现检查后，才能重新评估三个 check；本记录不勾选任何 check。

## 治理限制

本记录不修改 `PB-0039` 状态，不修改三个验收布尔值，不授予交易权限，不把 `UNKNOWN`、`dirty`、`partial` 或 `not reproducible` 转换为完成。未执行 commit 或 push。
