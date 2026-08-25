# PB-0040 逐标的策略证据汇总（2026-08-25）

## 范围与合同

新增 `scripts/aggregate_instrument_strategy_evidence.py`，把已经完成的真实
SimulationService 回放汇总为 `data/instrument_strategy_evidence.json`。它不重新
选择参数，也不授予 Promotion；只统一输出标的、资产域、策略、OOS、成本后收益、
回撤、Sharpe、闭合交易数、稳定性、执行质量和 Promotion 原因。

目标合同固定为年化收益至少 50%、每个完整月收益至少 15%。缺少年/月证据时状态
为 `UNKNOWN`，不会当成 0 或 PASS；所有汇总结果仍然是 `research_only`。

## 当前结果

| 资产域 | 标的数 | 证据行 | 目标 PASS | 目标 FAIL | UNKNOWN |
|---|---:|---:|---:|---:|---:|
| 美股 | 27 | 27 | 0 | 27 | 0 |
| A 股 | 8 | 8 | 0 | 8 | 0 |
| 加密 | 18 | 36 | 0 | 0 | 36 |
| 合计 | 53 | 71 | 0 | 35 | 36 |

当前结果不能证明任何标的达到用户目标。美股和 A 股的独立固定资本回放已经有
年/月目标失败证据；加密多折和最新 walk-forward 回放有 OOS 结果，但缺少同口径的年化/月度目标与
稳定性字段，因此保持 UNKNOWN。所有交易的历史盘口深度仍未达到可执行证据门禁。

## 下一步

1. 为加密逐标的回放接入与股票相同的固定资本、月度目标和三折稳定性合同。
2. 对 35 个 FAIL 标的按交易成本、换手、负贡献时期和最大回撤分解，候选只能
   使用训练区间预注册，不能用 OOS 反选。
3. 对 36 条 UNKNOWN 加密证据优先补齐真实历史、费率和成交质量数据；在证据补齐前
   不调参、不晋级。

可重复入口：

```text
uv run --locked python scripts/aggregate_instrument_strategy_evidence.py
```
