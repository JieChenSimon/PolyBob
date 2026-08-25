# PB-0040 即时探针 + 2 日确认迭代（2026-08-25）

## 研究目的

针对“等待连续多日确认会错过抄底”的反馈，运行一个受约束的分批入场变体：50% 历史峰值回撤触发后先投入 1% NAV 探针，2 个交易日后再按既定分批规则继续入场。实验使用真实本地日线和 `SimulationService` 成交/费用/账本内核，未把缺失的历史盘口深度伪造成可成交。

本轮为 `deep_drawdown_rebound_v1` 的诊断性配置比较，不改变 `confirmation: none` 的预注册主合同，也不授予交易权限；结果只用于决定是否值得进行下一轮预注册验证。

## 覆盖与门禁

- 10 个标的：AMD、INTC、MRVL、NVDA、MU、SNDK、WDC、BTC-USDT、ETH-USDT、SOL-USDT。
- 4 个持有期 × 3 个成本倍数，共 **120/120** 个真实内核案例完成。
- 交易成本使用资产域配置的 1×/2×/3×压力；每个案例均记录成交、费用、回撤和执行诊断。
- 全局 Promotion 为 `BLOCKED`：严格历史 PIT、可执行报价深度和多标的独立 OOS 事件簇仍不足。

## 成本后 OOS 结果（1×成本）

| 标的 | 21 日 | 63 日 | 126 日 | 252 日 | 解释 |
|---|---:|---:|---:|---:|---|
| AMD | -0.13%（2） | +0.55%（1） | +3.12%（1） | +4.73%（1） | 长持有相对无探针基线小幅改善，但事件数不足 |
| INTC | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | 没有闭合 OOS 事件 |
| MRVL | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | 事件不在 OOS 或无法形成闭合 OOS |
| NVDA | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | 没有闭合 OOS 事件 |
| MU | +1.28%（1） | +3.07%（1） | +7.01%（1） | +19.76%（1） | 单一事件，不能外推或晋级 |
| SNDK | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | 事件/覆盖不足 |
| WDC | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | 没有闭合 OOS 事件 |
| BTC-USDT | -0.22%（1） | +0.12%（1） | UNKNOWN | UNKNOWN | 样本极少，且执行深度未知 |
| ETH-USDT | -0.07%（2） | -0.65%（2） | -0.92%（1） | UNKNOWN | 短中期为负 |
| SOL-USDT | -0.14%（2） | -0.19%（1） | UNKNOWN | UNKNOWN | 相比基线没有改善 |

括号内为闭合 OOS 事件数；`UNKNOWN` 不等于 0 收益。与相同数据上的无探针基线相比，AMD 的 126/252 日均仅改善约 0.28/0.34 个百分点，而 BTC 63 日下降约 0.18 个百分点、SOL 21/63 日分别下降约 0.18/0.27 个百分点。该方向没有跨资产一致性。

## 结论与下一步

1. 即时小探针没有解决收益目标：没有任何标的同时证明年化不少于 50%、每个完整月不少于 15%，也没有标的通过 OOS、独立性、PIT、可执行深度和多重检验门禁。
2. MU 的 252 日 +19.76% 只来自 1 个闭合 OOS 事件，不能被当成策略有效性证据；其余高回撤周期标的基本面字段仍不足，必须保持 `UNKNOWN_NO_TRADE`。
3. 该变体不应直接进入 Strategy Manager 或模拟盘自动交易。下一轮只有在补齐历史 PIT 基本面和报价/深度后，才预注册一个有限配置，按资产域分别做 walk-forward 与事件簇检验；不再用更多参数网格追逐单一正事件。

证据文件：`data/deep_drawdown_kernel_probe2_replay.json`，进度 `data/deep_drawdown_kernel_probe2_progress.json`，运行器 `scripts/deep_drawdown_kernel_replay.py`。
