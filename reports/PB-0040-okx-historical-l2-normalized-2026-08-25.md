# PB-0040：真实 OKX L2 订单簿重建与采样

已对本地真实 OKX BTC-USDT 400 档归档完成 snapshot/update 重建，生成可查询的 1 秒采样 Parquet：

- 原始行数：5,838,524
- snapshot：1,440
- update：5,837,084
- 无效记录：0
- 采样行数：86,400
- 覆盖：2025-08-01 UTC 全天
- BBO 交叉无效：0；关键字段缺失：0
- 采样数据：`data/datasets/parts/okx_historical_orderbook_sampled_1s/symbol=BTC-USDT/2025-08-01.parquet`
- 原始归档 SHA-256：`fbefa651de5b388da94ec5b0bce45f5a0fd26c1dd3c6be5ea0f88cd0c1a5f68d`

解析器保留原始 400 档归档，并对更新流重建买卖盘；规范化样本保留最佳买卖价、前 20 档深度、采样时间、更新计数和原始归档哈希。资源监控显示 CPU 约 16%–40%，中断不会留下半成品。

执行门禁当前为 `UNKNOWN` 而不是 READY：后续单日深度不平衡诊断已实现按模拟盘成交时间的 quote-observation 关联（590/590），但该数据仍只有 1 秒采样历史深度，尚未完成多日期覆盖、部分成交重放和精确序列级执行审计。系统现在显示 `sampled_historical_orderbook_has_partial_fill_linkage_but_insufficient_coverage`，不会把单日样本夸大为已验证的可成交收益。
