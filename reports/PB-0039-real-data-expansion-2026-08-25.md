# PB-0039 真实 BTC 5 分钟数据扩展记录

更新时间：2026-08-25（Asia/Singapore）

## 已完成

- 通过 OKX `market/history-candles` 拉取真实 BTC-USDT 1 分钟 K 线。
- 本轮请求 30,000 根 1 分钟 K 线，原始响应写入本地 data lake，记录 source、request、observed_at 和 SHA-256。
- 生成 `data/btc5m_calibration.json`：30,000 根原始 1 分钟 K 线、5,994 个可用 5 分钟窗口、22 个独立自然日。
- 真实波动率概率模型相对旧猜测波动率模型的 Brier score：
  - 决策后 1 分钟：0.2355 → 0.2195
  - 决策后 2 分钟：0.2197 → 0.1851
  - 决策后 3 分钟：0.2027 → 0.1471

## 仍未通过的门禁

- 这份结果的状态仍是 `calibration_only_not_trading_evidence`，不能据此宣称盈利或放行交易。
- 当前已提交的 BTC 5m settled-window 报告仍只有 3,545 个窗口；本轮 1m 校准数据尚未自动重建为与交易报告同一版本的 settled-window 数据集。
- 因此成本后成交、时间切分、逐日/逐月收益、回撤和 Promotion Board 验收尚未通过。
- 本轮数据中发现 normalized 1m dataset 可能存在跨 part 的重复时间戳，下一步必须先完成可重放去重/版本化，再进入交易收益审计。

结论：数据覆盖门槛已达到，但交易有效性结论仍为 `UNKNOWN`，不允许把校准改善当作收益改善。
