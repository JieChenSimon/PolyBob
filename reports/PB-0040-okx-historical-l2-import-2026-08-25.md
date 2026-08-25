# PB-0040：真实 OKX L2 历史资产导入

本轮已实际接入 OKX 官方历史数据下载接口，并将真实 BTC-USDT 400 档 L2 日归档保存到本地数据集原始层：

- 日期：2025-08-01 UTC
- 文件：`BTC-USDT-L2orderbook-400lv-2025-08-01.tar.gz`
- 压缩后大小：257,527,903 bytes
- 内容：gzip tar，逐行 JSON，包含 `snapshot`/`update`、毫秒级 `ts`、asks、bids 和深度字段
- SHA-256：`fbefa651de5b388da94ec5b0bce45f5a0fd26c1dd3c6be5ea0f88cd0c1a5f68d`
- 本地路径：`data/datasets/raw/okx_historical_orderbook_l2/…`
- manifest：`okx_historical_orderbook_l2_raw`，`history_scope=historical_orderbook_raw_archive`

新增 `scripts/import_okx_historical_l2.py`，支持官方下载链接查询、日期范围、400/5000 档、流式下载、大小上限、原子临时文件、SHA-256 和 manifest 登记。当前还没有把原始 update 流重建成可直接关联成交的规范化 BBO 数据，因此 Promotion 仍为 `BLOCKED`；下一步是以有界资源解析 snapshot/update、重建订单簿并验证缺口/序列连续性后再改变执行门禁。

OKX 官方历史数据页声明 L2 订单簿数据自 2023 年 3 月起可下载；本地这次导入的是该官方资产的真实文件，不是模拟或合成盘口。
