# PB-0040：真实 OKX 前向订单簿采集验证

本轮把实时深度采集器扩展为有界、可重启的前向采集流程，并通过真实 OKX 公共接口完成了一次验证：BTC-USDT、ETH-USDT、SOL-USDT，20 档，2 次轮询，间隔 2 秒，每次 3 条真实深度记录，checkpoint 最终状态为 `completed`。

每条记录保留真实 `event_at`、`observed_at`、`best_bid`、`best_ask`、20 档买卖深度、层数、序列号、来源和 `history_scope=live_observation`。重复抓取通过内容地址和 Parquet 分区去重；轮询次数和 checkpoint 有界，不生成无界日志或进程。

这产生的是从现在开始积累的 `forward_real_observation`，不是对过去的历史回填。因此历史回测的可成交报价门禁仍然是 `UNKNOWN`，不能把这次采集当作已经具备历史 BBO/深度证据。只有当未来积累覆盖了相应回放区间、并能按成交时间关联深度和部分成交时，才允许重新评估该门禁。

代码测试：`tests/test_collect_okx_orderbook.py` 与 readiness 测试共 6 项通过。
