# SEC insider 策略真实数据优化复核

本轮使用 SEC Form 345 2024Q1–2026Q2，实际落盘 762,258 条交易，事件涉及 3,010 只股票。价格覆盖为 2,527/3,010（84.0%）；无法定价的事件保留为 dropped，不填零收益。

正式预注册结果（20 日、至少 2 位内部人、单笔至少 $50k）如下：

- 集群买入：2,305 个可定价事件，平均超额收益 -38.09%，中位数 -22.02%，胜率 26.2%，月度聚类 t=-3.88。
- 单人买入对照：4,472 个可定价事件，平均超额收益 -49.20%，中位数 -22.28%，胜率 25.2%，月度聚类 t=-4.09。
- 两组都没有通过多重检验门槛；“集群比单人更强”没有得到本样本支持。

随后运行 18 组受约束候选，只用 2024–2025 训练期选参，2026 作为固定 OOS：

- 训练期选出的仍是原候选：20 日、至少 2 人、至少 $50k。
- 2026 OOS：844 个事件，平均超额收益 +1.139%，中位数 +0.076%，聚类 t=1.35，wild-bootstrap p=0.285，95% bootstrap 区间 [-0.409%, 2.556%]。
- 结论：弱正但统计不显著，不能晋级、不能进入实盘；OOS 最好的候选也不能反向替代训练期选择。

优化器：[insider_strategy_optimization.py](../scripts/insider_strategy_optimization.py)，证据：[insider_optimization_results.json](../data/insider_optimization_results.json)。

SEC 数据源使用官方的 [Insider Transactions Data Sets](https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets)，事件时间使用公开披露日而不是成交日。这个区别是防止 look-ahead 的硬约束。
