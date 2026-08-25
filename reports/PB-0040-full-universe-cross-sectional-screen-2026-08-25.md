# PB-0040 全量自主发现宇宙横截面 screen（2026-08-25）

## 范围

本轮使用完整自主发现 manifest，并在 Yahoo 复权 OHLCV 刷新后重新验证：

- A 股：freshness 门禁后的 8 个 READY 标的进入 screen；其余历史数据已 stale
  或缺少本地覆盖，不再视为当前可研究成员。
- 美股：31 个 READY 标的中 7 个因本地价格序列质量门禁被拒绝，24 个进入
  screen 和 Paper Lab。
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

8 个 READY 标的仍少于 20 个同期基准门槛；
本轮结果为 UNKNOWN/BLOCKED，不再引用此前基于 8 个标的的收益数值。

### 美股

允许 5 行向后取价后，24 个标的可参与同期基准。训练期选出的组合为
`lookback=60, top_frac=0.2, rebalance=5, vol_target_10`；训练期超额
`+169.61%`，但严格 OOS 组合收益 `+38.90%`，同期等权基准 `+49.48%`，
OOS 超额 `-10.57%`。因此候选被标记 `tested_no_edge`，没有 Promotion。

随后把同一训练期候选接入真实本地数据 Paper Lab：组合回放总收益 `+90.91%`、
最大回撤 `14.95%`，但年化目标门禁 FAIL（约 `14.62%`），且 1,424 笔交易的
盘口深度全部 UNKNOWN。绝对收益为正不等于跑赢基准，也不等于可执行的真实交易
优势，所以最终状态仍是 `replay_only_not_promoted`。

## 决策

全量自主发现扩大了覆盖面；美股的价格基准、交易日对齐和 Paper Lab 链路已重新
验证，但策略样本外仍落后基准且执行深度证据缺失。A 股仍缺少至少 20 个同期可
比较标的，继续 UNKNOWN。本轮不 Promotion。下一步优先扩充有质量门禁的历史
覆盖、补齐真实盘口/报价观测，并对负贡献标的做逐标的归因后再提出受约束候选。

## 可复现产物

- 输入：`data/discovered_equity_universe_full.json`
- 未加门禁的诊断输出：`/tmp/polybob_full_cross_sectional_screen.json`
- 加同期基准门禁的权威输出：`/tmp/polybob_full_cross_sectional_screen_gated.json`
- 处理交易日历差异后的权威输出：`/tmp/polybob_full_cross_sectional_screen_stale5.json`
- freshness 门禁后重跑的权威输出：`/tmp/polybob_full_cross_sectional_screen_fresh.json`
- 运行器：`scripts/cross_sectional_local_screen.py`
- 真实数据、成本后、训练选择与滚动折叠结果均保存在运行输出中。
- 复权数据 Paper Lab：`/tmp/polybob_adjusted_us_paper.json`
- 复权数据 screen：`/tmp/polybob_cross_sectional_adjusted.json`
