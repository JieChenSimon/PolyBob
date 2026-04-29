# Cross Market Dislocation Strategy V1

## 策略概述

跨市场错位套利策略,基于统计套利原理,捕捉相关市场间的价格错位机会。

## 核心逻辑

1. **价差监控**: 实时监控所有市场对的价格差异
2. **统计分析**: 计算价差的历史均值和标准差
3. **信号触发**: 当价差超过均值 ± N 个标准差时触发信号
4. **均值回归**: 假设价差会回归到历史均值

## 参数说明

- `z_score_threshold`: Z-score 阈值,默认 2.0
- `min_spread_bps`: 最小价差(基点),默认 50.0
- `lookback_window`: 回看窗口大小,默认 100
- `signal_ttl_seconds`: 信号有效期(秒),默认 300

## 信号生成

当满足以下条件时生成信号:
- |Z-score| > z_score_threshold
- |价差| > min_spread_bps

信号方向:
- Z-score > 0: 做空高价市场,做多低价市场
- Z-score < 0: 做多高价市场,做空低价市场

## 风险控制

- 固定仓位大小(由风控模块动态调整)
- 信号有效期限制
- 最小价差要求

## 使用示例

```python
from strategies.cross_market_dislocation_v1.strategy import CrossMarketDislocationV1

config = {
    "z_score_threshold": 2.0,
    "min_spread_bps": 50.0,
    "lookback_window": 100,
    "signal_ttl_seconds": 300,
}

strategy = CrossMarketDislocationV1(config)
await strategy.start()
```
