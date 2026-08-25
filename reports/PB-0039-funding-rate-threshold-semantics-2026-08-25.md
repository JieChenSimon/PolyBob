# PB-0039 资金费率阈值语义与真实性核对（2026-08-25）

## 结论

`60/75/90` 不是 60%、75%、90% 的资金费率，也不是“预支”比例；它们是滚动 30 日历史
分位数阈值：

- `60`：当前费率高于历史 P60 做空，低于 P40 做多；
- `75`：当前费率高于 P75 做空，低于 P25 做多；
- `90`：当前费率高于 P90 做空，低于 P10 做多。

代码已经将名称从 `threshold_pct` 改成 `threshold_percentile`，并在报告中写明“percentile
rank，不是 funding-rate percentage”；传入 `0.75` 这类费率式数值现在会直接失败。

## 本地真实数据核对

当前回放读取 `data/store/funding_rates` 中的 `BTC-PERPETUAL` 和 `ETH-PERPETUAL`，使用
`deribit_interest_8h_settlement_daily_sum_v2`：从 Deribit 官方
`public/get_funding_rate_history` 的真实 hourly 响应中取 UTC 00:00/08:00/16:00 三个
`interest_8h` 结算点求和，并以真实 `funding_rate` 快照传给 `SimulationService`。
不完整首尾日被排除；旧的 `interest_1h` 日汇总只保留为历史 provenance，不再进入新回放。

| 标的 | 最小日汇总 | 最大日汇总 | 换算后的实际范围 |
|---|---:|---:|---:|
| BTC-PERPETUAL | -0.0003243 | 0.0010428 | -0.03243% 至 0.10428% |
| ETH-PERPETUAL | -0.0006096 | 0.0006282 | -0.06096% 至 0.06282% |

因此用户对“没有 60% 那么高”的判断是对的：实际费率远低于 1%，此前报告字段容易造成
误读，现已修正。历史报告里的 `threshold_pct` 字段应按分位数解释，不应按费率百分比解释。

## 数据边界

这是 Deribit BTC/ETH 永续合约的真实费率，不代表 Binance、OKX 或其他山寨币交易所的费率。
当前资金费率策略也没有通过收益、稳定性和成本压力门禁；语义修正不等于策略有效。
