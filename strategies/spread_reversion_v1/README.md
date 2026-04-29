# Spread Reversion Strategy V1

## 策略概述

价差回归策略,捕捉异常宽价差的收敛机会。当买卖价差超过历史均值时,预期价差会回归正常水平。

## 核心逻辑

1. **价差监控**: 实时监控每个市场的买卖价差
2. **异常检测**: 识别价差异常扩大的市场
3. **深度验证**: 确保有足够的订单簿深度支持交易
4. **做市机会**: 在价差中间价位挂单,赚取价差收益

## 参数说明

- `spread_threshold_bps`: 价差阈值(基点),默认 150.0
- `reversion_confidence`: 回归置信度,默认 0.7
- `min_depth_ratio`: 最小深度比率,默认 0.3
- `signal_ttl_seconds`: 信号有效期(秒),默认 180

## 信号生成

当满足以下条件时生成信号:
- 价差 > spread_threshold_bps
- 深度不平衡 < min_depth_ratio (订单簿相对平衡)
- 有足够的流动性支持

信号策略:
- 在中间价附近挂限价单
- 预期价差收敛时获利

## 风险控制

- 深度验证避免流动性陷阱
- 信号有效期限制
- 固定仓位大小

## 使用示例

```python
from strategies.spread_reversion_v1.strategy import SpreadReversionV1

config = {
    "spread_threshold_bps": 150.0,
    "reversion_confidence": 0.7,
    "min_depth_ratio": 0.3,
    "signal_ttl_seconds": 180,
}

strategy = SpreadReversionV1(config)
await strategy.start()
```
