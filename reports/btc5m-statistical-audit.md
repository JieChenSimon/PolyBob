# BTC 5m statistical audit

结论：**UNKNOWN**。正收益不等于可推广；当前门禁必须保持 UNKNOWN。

- 事件数：2216；独立日期：12；独立月份：1
- 聚类 t：33.005；wild bootstrap p：0.0005；p floor：0.00048828125
- 多重检验：255 trials；t hurdle：4.2033

## 门禁

- cluster_inference: UNKNOWN
- wild_bootstrap: UNKNOWN
- date_train_validation_test: UNKNOWN
- month_train_validation_test: UNKNOWN
- oos_stability: UNKNOWN
- drawdown: UNKNOWN
- return_target: UNKNOWN

## 缺失/降级

- event report stores date, not an exact decision timestamp; ordering is date plus entry price
- month split is unavailable until at least three independent months exist, and return targets need twelve complete months
- wild bootstrap p is reported but cannot override the cluster floor or unresolved p resolution
- drawdown has no pre-registered BTC threshold and is not a fill-accurate portfolio curve

## 判定原则

日期与月份均按独立日历标签切分，先切分再做聚类推断；任何分区少于 20 个独立簇均为 UNKNOWN。wild bootstrap、正均值和正 OOS 均不能绕过该门禁。

## 下一轮验收记录（2026-08-25）

本记录只补充治理证据，不改变 `PB-0039` 的状态或任何 check。当前任务仍为 `DOING`，验收为 `0/3`；`UNKNOWN`、`partial` 和 `not promotable` 均不得解释为完成。

### 当前证据快照

- 任务看板：`tasks/items/PB-0039.yml`；分支为 `pb-0037-funding-strategy-replay`，第 2、3 项仍未完成。
- 错价报告：`data/btc5m_mispricing.json`；`3145` 个 settled windows、`2216` 个 qualifying trades，采集状态为 `partial`，预算耗尽且结果仍不完整。
- 报告 manifests：`data/btc5m_calibration.manifest.json`、`data/btc5m_direction_kernel_replay.manifest.json`、`data/btc5m_event_kernel_replay.manifest.json` 已补齐；三者均显式记录 `pit_status=UNKNOWN` 和非可交易/诊断限制。
- Promotion Board：`data/promotion_board.json`；`approved_trade=0`；BTC 5m 为 `approved=false`，`n_clusters=12`，失败原因为 `collection_partial`、`independent_clusters<20` 和 `no_pit_contract_cannot_trade`。
- 事件回放：`data/btc5m_event_kernel_replay.json` 标记为 `diagnostic_not_promotion`；即使成本压力下出现正的单月结果，收益目标仍为 `UNKNOWN`，原因是只有 1 个完整月份而门禁要求 12 个月。
- 提交链：相关证据提交在 `5eb1e26` 及其父提交，带 `PolyBob-Task: PB-0037` 和 `PolyBob-Task: PB-0039`；共享分支归属仍需后续交接记录说明。
- 新增 paper fill quote provenance：成交记录保存 bid/ask、深度、quote source、raw provenance 和 quote quality；synthetic stress 仍明确标记为不可交易。
- 验证：`dev_control validate`、Promotion Board 一致性检查和 snapshot audit 均通过；完整测试必须在本轮所有改动提交后重跑。

### 下一轮必须通过的门禁

1. 固定同一数据快照和 `as_of`，对 calibration、direction、event kernel、mispricing 使用同一时间切分，并记录输入 hash。
2. 已为 calibration、direction、event kernel 补齐与报告一一对应的 manifest；仍需在同一数据快照上统一时间切分并持续更新。
3. 重新生成逐日、逐月、最大回撤、成本敏感性、未平仓和降级状态审计；不足 12 个完整月份时，`return_target` 必须继续为 `UNKNOWN`。
4. 重新构建 Promotion Board；在独立聚类达到门槛且 PIT 合同可解析前，BTC 5m 必须保持 `approved=false`，不得授予开仓权限。
5. 补充 PB-0039 专属数据、量化、执行和治理 reviewer 交接记录，并在提交链中明确 PB-0037/PB-0039 的共享分支关系。
6. 提交前运行完整测试套件、lineage/manifest 测试、Promotion Board 重建检查和真实数据复现检查；只有证据和门禁都满足时，才重新评估第 2、3 项 check，不能由本记录直接勾选完成。
