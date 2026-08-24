# 真实数据模拟盘研究流水线

任务：PB-0027  
运行时间：2026-08-24  
证据文件：[simulation_research_report.json](../data/simulation_research_report.json)

## 本轮实际执行

`scripts/simulation_research_pipeline.py` 使用本地 bitemporal `daily_bars` 数据，逐标的建立独立模拟盘 run，并调用现有 `SimulationService` 的同一套：

- `momentum_dualma_v1` 信号源；
- mid-only 历史报价的保守成交路径；
- 手续费、mid penalty、sqrt impact、仓位比例；
- 风险检查、持仓平均价、成交账本、权益曲线和回撤；
- 真实数据源、价格基准、PIT `as_of` 和运行 manifest。

历史回放只注入事件时钟，不改变模拟盘的交易逻辑。这样 2020/2021 年历史事件不会被当前墙上时钟错误判为 stale，同时仍然执行模拟盘的 freshness、成本和风险规则。

## 全量结果

本地日线数据集：2843 个标的、9,036,974 行，日期范围 2021-07-26 至 2026-08-21。补齐 SEC 事件股票价格后，美股覆盖从 1426 扩展到 2715，结果没有因此变好。

| 资产域 | 标的数 | 暂时 PASS | FAIL | 数据不足 BLOCKED | 平均总收益 |
| --- | ---: | ---: | ---: | ---: | ---: |
| A 股 | 62 | 2 | 60 | 0 | -0.55% |
| 美股 | 2715 | 23 | 2595 | 97 | -5.16% |
| 加密货币 | 66 | 19 | 43 | 4 | +0.73% |

失败主要原因是：平仓样本少于 20 笔、总收益非正、少数标的最大回撤超过 25%。这些不是程序错误，而是策略证据不足或策略表现不达标的真实结果。

## 参数优化规则

预先声明的候选族为 4 组双均线参数。A 股、美股、加密货币分别只在训练期比较平均收益，再把训练期选出的候选固定到 OOS 验证和该域诊断；OOS 结果不能反过来选参。此前版本曾错误地用 OOS 选择参数，已修复并加入回归测试。失败归因只生成受约束的下一步候选建议：

- 非正收益：测试更慢趋势窗口、更严格分离阈值，并检查换手和成本拖累；
- 成交样本不足：只在校准集放宽分离阈值，并延长独立 OOS 观察期；
- 回撤过高：测试更低仓位比例和波动/回撤上限；
- 权益曲线 degraded 或未知：先修复行情标记覆盖，不允许优化策略掩盖数据问题。

本轮的候选选择只是诊断用途。多重检验门槛记录了 4 次候选试验，对应 deflated t 门槛约 3.30。最终共同 OOS 收益矩阵的 PBO 为：A 股 0.5992（overfit）、美股 0.7738（overfit）、加密货币 0.6389（overfit），整体晋级状态仍为 BLOCKED。修复后的训练/OOS 选择逻辑需要重新跑全量报告，旧报告的候选选择结果不再作为有效 OOS 证据。

本轮实际跑的是 `momentum_dualma_v1` 的 4 组预注册参数候选，不等同于系统中所有策略都已经验证。`signal_fusion`、价差均值回归/套利以及依赖资金费、盘口的策略仍需各自接入兼容的真实数据回放和独立 OOS 门禁；SEC insider 已有独立报告。报告不把它们伪装成已完成。

## 尚不能下结论的数据线

- BTC 5 分钟：本地 `btc_1m_bars` 只有 314 行，不能代表大规模历史窗口；不能用 Binance 451 限制或缺失数据替换成模拟数据。
- SEC insider：已落盘 2024Q1–2026Q2 的 762,258 条 Form 3/4/5 交易；独立 insider 事件研究已完成，但当前结果仍未通过 OOS/聚类推断门禁。
- 资金费、盘口深度和公司行动：覆盖不足时对应的收益和风险指标必须保持 UNKNOWN 或进入阻断，而不是填零。

## 下一轮必须完成的门禁

1. 已建立每个资产域的共同时间轴候选收益矩阵并计算 PBO；仍需补充 DSR/deflated t 的实际观测统计量和 block-bootstrap/独立日历簇置信区间。
2. 对候选只在校准集调参，在完全独立的 OOS 时间段复测；当前全量报告的 `full_results` 是候选选择后的全历史诊断，不能替代最终 OOS 证明。
3. 为 BTC 5 分钟、SEC insider 和资金费补齐真实、可重放、带来源和观察时间的数据后再运行对应策略。
4. 只有通过样本量、成本后收益、最大回撤、稳定性、PBO/DSR 和独立 OOS 的组合门禁，才允许进入 promotion board；本轮没有任何策略被提升。

## 方法依据

- Bailey 与 López de Prado 的 Deflated Sharpe Ratio 用于修正多重试验选择偏差和非正态收益；见 [SSRN 原始论文](https://doi.org/10.2139/ssrn.2460551)。
- Purging 与 embargo 用于避免金融时间序列标签重叠和序列相关造成的信息泄漏；见 [Financial ML Core 的方法实现说明](https://ppuertos.github.io/financial-ml-core/reference/model_selection/split/)。
- 加密历史 K 线的时间主键、区间参数和 UTC 解释遵循 [Binance 官方 Spot API 文档](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md)；本项目当前运行中因网络区域限制使用已有本地真实数据，不以 451 错误替代数据。

## 本轮清理

仅清理了可再生构建产物：Next `.next`、dashboard `output`、Rust `target`、`dist`、测试/静态分析缓存和项目源码下的 `__pycache__`，约释放 400MB。`data/market_cache`、`data/store`、`data/datasets`、真实数据报告、manifest、promotion board 和 `apps/dashboard/archive` 均保留：前者是可重建但当前研究仍依赖的本地数据基座，后者有明确的归档索引，不能按“看起来旧”删除。
