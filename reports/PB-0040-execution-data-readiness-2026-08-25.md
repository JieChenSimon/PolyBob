# PB-0040：真实执行数据与生存偏差门禁审计

本轮对当前 `data/` 实际文件和数据集 manifest 做只读审计，并运行项目的 fail-closed readiness audit。

| 门禁 | 结果 | 证据 |
|---|---|---|
| 严格历史 PIT | UNKNOWN | daily bars/fundamentals 合同仍未声明 strict historical PIT |
| 退市/生存偏差 | UNKNOWN | 没有独立的 PIT listing/delisting 数据集 |
| 历史可成交 BBO/深度 | UNKNOWN | historical quote entries = 0 |

当前本地只有 3 条 OKX order-book 数据：BTC-USDT、ETH-USDT、SOL-USDT 各一条，全部是 `live_observation`，不是历史回放数据。它们可以用于实时系统健康检查，但不能证明股票、A 股或加密历史回放中的成交价格、深度、部分成交或滑点。

外部核对：OKX 官方历史数据页声明可下载自 2023 年 3 月起的高分辨率 L2 订单簿数据；当前项目尚未把该下载资产导入本地规范化数据集，因此不能把“官方存在下载服务”当成本地已具备证据。

审计结果：`promotion=BLOCKED`。因此回撤策略即使在日线 close 上有正收益，也不能晋级为真实交易候选。下一项可执行工作是接入带时间戳、原始 payload、深度层级、序列号和 instrument lifecycle 的真实历史数据源；数据未达到 READY 前，策略参数保持冻结，不继续围绕未知执行条件调参。

机器可读证据：`data/evidence_readiness_audit-2026-08-25.json`。
