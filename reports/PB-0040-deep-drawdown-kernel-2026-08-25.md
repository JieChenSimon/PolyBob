# PB-0040 深回撤候选真实模拟盘内核回放

## 结论

本轮把 `deep_drawdown_rebound_v1` 从原先的诊断性 `next_open → close` 计算接入真实 `SimulationService`：因果维护历史峰值，回撤首次达到 50% 后按下一根、+5 根、+20 根分批目标仓位，分别在 21/63/126/252 个交易日后发出平仓信号；手续费按资产域成本的 1×/2×/3× 压力运行，成交、现金、持仓和权益都经过同一 Paper Lab 账本。

共完成 **43 个标的 × 4 个持有期 × 3 个成本倍数 = 516 个案例**，耗时约 13.7 分钟，进度为 516/516。Promotion 仍为 BLOCKED：严格历史 PIT 基本面、历史可成交盘口/深度、幸存者偏差控制和足够独立 OOS 事件簇均未满足。

## 覆盖与样本质量

| 资产域 | 标的数 | 发生过 50% 事件的标的数 | 有 OOS 已闭合事件的案例数 | 判断 |
|---|---:|---:|---:|---|
| A 股 | 8 | 1 | 3 | 000858 仅有极少事件且成本后为负；其余本地窗口没有触发事件 |
| 美股 | 26 | 12 | 45 | TSLA/AMD/DIS/F 等部分窗口为正，但 OOS 事件通常仅 1–2 个，不能晋级 |
| 加密 | 9 | 9 | 54 | OOS 结果分化，多个币种转负；BTC 只有单一事件，证据不足 |

本地日线覆盖主要从 2023 年末开始，导致“没有事件”不能解释为“策略没有风险”，只能标为样本覆盖不足或 UNKNOWN。所有无事件、未平仓事件和无 OOS 事件都没有被当成 0 收益。

## 代表性结果

标准成本 1×下的部分全样本事件均值：NVDA 126d +3.961%、TSLA 252d +3.248%、AMD 252d +3.072%、BCH-USDT 126d +3.029%；但这些都是少量事件的诊断性统计，并不等同年化收益。

更重要的样本外结果：TSLA 252d OOS 约 +4.013%（1 个事件）、AMD 252d 约 +4.386%（1 个事件）、DIS 126d 约 +1.450%（1 个事件）；而 NKE 252d OOS 约 -2.168%、ADA-USDT 126d 约 -1.591%、LTC-USDT 126d 约 -0.930%。独立事件数远低于多重检验和稳定性门槛，不能据此选择赢家。

## 关键问题与下一轮

1. “回撤超过 50%”不是充分信号。没有 PIT 基本面质量、幸存者控制和可成交深度时，系统必须 `UNKNOWN_NO_TRADE`，不能自动重仓。
2. 当前 5% NAV 最大仓位的事件收益大多只有小数个百分点，远低于每个标的年化 50%/完整月份 15%硬门槛；不能通过放大仓位制造 alpha。
3. 下一轮只允许测试预注册状态过滤：基本面质量通过、流动性/盘口可成交、市场状态恢复、分批仓位上限和最大持有期；每个标的重新做独立 OOS、成本压力和事件聚类门禁。
4. 对本地历史不足的 A 股和 BTC 标的，优先补充可追溯历史数据；在补齐前保持 `UNKNOWN`，不把少量事件正收益升级成候选。

## 复现与验证

- 完整本地证据：`data/deep_drawdown_kernel_replay.json`。
- 进度：`data/deep_drawdown_kernel_progress.json`，最终 `completed_runs=516`。
- 内核适配：[modules/simulation/sources.py](/Users/SimonChen/workspace/codespace/PolyBob/modules/simulation/sources.py)。
- 回放器：[scripts/deep_drawdown_kernel_replay.py](/Users/SimonChen/workspace/codespace/PolyBob/scripts/deep_drawdown_kernel_replay.py)。
- 相关测试：39 passed；`dev_control validate`：`OK 44 tasks`。
