# PB-0040 全量自主发现宇宙横截面 screen（2026-08-25）

## 范围

本轮使用完整自主发现 manifest，而不是此前限额的 41 个标的：

- A 股：55 个 READY 标的全部进入 screen。
- 美股：1,364 个 READY 标的中 202 个因本地价格序列存在未解析跳变被拒绝，
  1,162 个进入 screen。
- 加密资产：完整 manifest 不包含加密标的，保持独立 crypto 数据管线，未混入
  股票横截面。

每个域都测试 54 个预注册组合（lookback 20/30/60、top fraction 20%/30%、
rebalance 1/5/10 日、raw/vol-target/drawdown 风控），候选只按训练期超额选择，
OOS 没有参与选参。

## 初始审计发现

未加同期基准门禁的初步输出暴露了数据问题：美股 OOS 起点为
`2025-02-14`，终点为 `2026-08-24`，1162 个进入 screen 的标的中只有
3 个同时有两端价格（`SNDK`、`MU`、`WDC`），所以等权基准 `+1861.70%`
并不是有效的全市场基准。A 股同期有效基准标的也只有 8 个。

## 加同期基准门禁后的结果

新增固定门禁：OOS 基准必须至少有 20 个同期可比较标的；否则整个域标记
`blocked_insufficient_contemporaneous_universe`，不产生收益或 alpha 结论。
同时允许最多向前端点回看 5 个已知矩阵行，只用于处理交易所假日和 UTC 收盘
日期差异；不会向未来取价。这样避免把美股 2026-08-24 只有少数标的收盘、
而多数标的最后观测在 2026-08-21 的情况误判为缺失。

### A 股

55 个 READY 标的中只有 8 个满足 OOS 起止日都有价格，低于 20 个门槛；
本轮结果为 UNKNOWN/BLOCKED，不再引用此前基于 8 个标的的收益数值。

### 美股

允许 5 行向后取价后，1162 个标的可参与同期基准，OOS 等权基准约为
`+33.96%`；但 54 个组合没有一个训练期超额为正，最好的训练期超额仍为
`-6.97%`，因此没有候选进入 Paper Lab。该结果也不构成 50% 年化证据。

## 决策

全量自主发现扩大了覆盖面；美股的基准时间对齐问题已修复，但策略仍没有
训练期优势。A 股仍缺少至少 20 个同期可比较标的，继续 UNKNOWN。本轮不启动
全量 Paper Lab，也不 Promotion。下一步优先修复美股价格基准/拆并股、A 股
历史覆盖和 survivorship 审计，再做固定样本外 screen。

## 可复现产物

- 输入：`data/discovered_equity_universe_full.json`
- 未加门禁的诊断输出：`/tmp/polybob_full_cross_sectional_screen.json`
- 加同期基准门禁的权威输出：`/tmp/polybob_full_cross_sectional_screen_gated.json`
- 处理交易日历差异后的权威输出：`/tmp/polybob_full_cross_sectional_screen_stale5.json`
- 运行器：`scripts/cross_sectional_local_screen.py`
- 真实数据、成本后、训练选择与滚动折叠结果均保存在运行输出中。
