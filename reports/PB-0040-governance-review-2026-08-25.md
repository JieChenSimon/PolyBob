# PB-0040 治理与产品血缘记录

复核日期：2026-08-25（Asia/Singapore）  
结论：**候选 / UNKNOWN / 禁止交易**

## 事实来源

- 任务：`tasks/items/PB-0040.yml`，状态 `doing`，验收 `0/3`，依赖 `PB-0039`。
- 研究合同：`config/research/deep_drawdown_rebound.yaml`，`strategy_id=deep_drawdown_rebound_v1`，`status=candidate_only`，`promotion_default=unknown`。
- 假设注册：`data/hypothesis_registry.json`，`hypothesis_id=deep_drawdown_rebound_v1`，`result=null`。
- 预注册脚本：`scripts/register_deep_drawdown_candidate.py`。
- 关联提交：`f67e77b` 带 `PolyBob-Task: PB-0040`、`PB-0039`、`PB-0037`；任务现绑定实际分支 `pb-0037-funding-strategy-replay`。该分支为共享任务分支，不能单独证明 PB-0040 已完成。

## 一致性审计

| 层 | 当前状态 | 治理判断 |
|---|---|---|
| 任务板 | `DOING 0/3` | 正确，不能完成 |
| 策略/假设注册 | 已注册为 `candidate_only`，无 result | 候选存在，但无研究结论 |
| Promotion Board | 仅计入预注册无结果的试验数，无 PB-0040 交易行 | 正确；不可手工添加交易许可 |
| Strategy Manager | 无 `deep_drawdown_rebound_v1` 模板/工厂 | 未接入运行时 |
| 前端策略卡 | 无专属 PB-0040 卡片或交易动作 | 应显示为未接入/UNKNOWN，而不是可交易 |
| 模拟盘 | 无 PB-0040 专属 source/preset/replay | 未接入模拟盘工作流 |

Promotion Board 当前 `approved_trade=0`。PB-0040 没有可交易证据，也没有报告 manifest；不存在可供晋级的收益、成本、样本外或风险结果。

## 下一轮必须补齐

1. 建立 PB-0040 专属真实数据报告及 manifest，manifest 必须绑定报告 hash、输入数据 hash、代码 commit、dirty 状态、PIT/生存者偏差状态和资产域覆盖。
2. 以 A 股、美股、BTC、山寨币四个 sleeve 分域完成 50% 回撤触发、三段入场、21/63/126/252 日持有期、成本/滑点、最大回撤、资金占用、破产和无法成交统计。
3. 通过独立性、多重检验、训练/验证/样本外、成本压力和组合风险门禁后，才允许生成 Promotion Board 候选；否则保持 `UNKNOWN/NO_EDGE`。
4. 在 Strategy Manager、前端策略目录和模拟盘接入前，产品状态必须统一为 `candidate_only`、`UNKNOWN`、`trade_permission=false`；不得创建可启动的交易实例或开仓意图。
5. 补齐 PB-0040 reviewer 交接，并在共享分支提交链中保留 PB-0040 trailer；提交前重新运行任务校验、报告 lineage 校验、Board 重建和相关前端/模拟盘测试。

本记录不勾选任何 PB-0040 check，不修改 Promotion Board，不授予交易权限，不执行 commit 或 push。
