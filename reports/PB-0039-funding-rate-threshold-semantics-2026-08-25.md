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

当前回放读取 `data/store/funding_rates` 中的 `BTC-PERPETUAL` 和 `ETH-PERPETUAL`，全部 401
条记录的 source 都是 `deribit_interest_1h_daily_sum`，覆盖 2025-07-20 至 2026-08-24。
该数据由 Deribit 官方 `public/get_funding_rate_history` 的 hourly `interest_1h` 按 UTC 日求和，
并以真实 `funding_rate` 快照传给 `SimulationService`；模拟盘开启 funding ledger，按日结算。

| 标的 | 最小日汇总 | 最大日汇总 | 换算后的实际范围 |
|---|---:|---:|---:|
| BTC-PERPETUAL | -0.0003394 | 0.0009223 | -0.03394% 至 0.09223% |
| ETH-PERPETUAL | -0.0005548 | 0.0006089 | -0.05548% 至 0.06089% |

因此用户对“没有 60% 那么高”的判断是对的：实际费率远低于 1%，此前报告字段容易造成
误读，现已修正。历史报告里的 `threshold_pct` 字段应按分位数解释，不应按费率百分比解释。

## 数据边界

这是 Deribit BTC/ETH 永续合约的真实费率，不代表 Binance、OKX 或其他山寨币交易所的费率。
当前资金费率策略也没有通过收益、稳定性和成本压力门禁；语义修正不等于策略有效。
