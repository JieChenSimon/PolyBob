# Strategy Engine - 策略引擎

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                    Strategy Engine Service                   │
│  - 订阅特征快照                                               │
│  - 并发执行所有策略                                           │
│  - 发布交易信号                                               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────────┐
        │         Strategy Base Class              │
        │  - generate_signal(features) -> Signal   │
        └─────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   数学模型    │    │   数学模型    │    │  AI 模型     │
│ Spread       │    │ Statistical  │    │ AI Signal    │
│ Reversion    │    │ Arbitrage    │    │ Generator    │
└──────────────┘    └──────────────┘    └──────────────┘
```

## 核心组件

### 1. Strategy Base (`base.py`)

**StrategySignal** - 信号输出标准
- `market_id`: 市场 ID
- `side`: 交易方向 (BUY_YES/SELL_YES/BUY_NO/SELL_NO)
- `price`: 目标价格
- `size`: 交易数量
- `confidence`: 置信度 (0-1)
- `expected_edge_bps`: 预期优势 (基点)
- `reason`: 信号原因

**Strategy** - 策略基类
- `generate_signal(features)`: 核心方法,返回信号或 None

### 2. 数学模型策略

#### Spread Reversion Strategy (`spread_reversion.py`)
**原理**: Bollinger Bands 价差回归
- 价差 = ask - bid
- 当价差 > 均值 + k*std 时,预期回归
- 做市机会: 同时挂买卖单赚取价差

**参数**:
- `lookback_window`: 60 (历史窗口)
- `entry_threshold_std`: 2.0 (进场阈值)
- `min_spread_bps`: 50.0 (最小价差)

**数学公式**:
```
z_score = (spread_current - spread_mean) / spread_std
if z_score > threshold:
    signal = BUY (预期价差收窄)
```

#### Statistical Arbitrage Strategy (`statistical_arbitrage.py`)
**原理**: 相关市场定价偏差套利
- 寻找高相关市场对 (corr > 0.7)
- 计算价差 z-score
- 价差过大时做空高估/做多低估

**参数**:
- `correlation_threshold`: 0.7
- `entry_threshold_std`: 2.5

**数学公式**:
```
correlation = cov(X, Y) / (std(X) * std(Y))
spread = price_A - price_B
z_score = (spread - mean_spread) / std_spread
if |z_score| > threshold:
    signal = LONG_CHEAP / SHORT_EXPENSIVE
```

#### Kelly Position Strategy (`kelly_position.py`)
**原理**: Kelly Criterion 最优仓位
- 根据胜率和赔率计算最优仓位
- 使用 fractional Kelly (0.25x) 降低风险

**参数**:
- `kelly_fraction`: 0.25 (保守 Kelly)
- `min_edge_bps`: 30.0
- `depth_imbalance_threshold`: 0.3

**数学公式**:
```
Kelly = (p * b - q) / b
其中:
  p = 胜率 (基于深度不平衡估计)
  q = 1 - p
  b = 赔率 (基于价差估计)

position_size = Kelly * kelly_fraction * max_position
```

### 3. AI 信号生成器 (`ai_signal_generator.py`)

**工作流程**:
1. 将市场特征转换为结构化 prompt
2. 调用 LLM (如 Claude) 生成决策
3. 解析 JSON 响应为标准信号

**Prompt 模板**:
```
输入:
- 市场特征 (价格、价差、深度、成交量等)
- 市场问题描述

输出 JSON:
{
  "action": "buy_yes" | "sell_yes" | "no_trade",
  "confidence": 0.0-1.0,
  "expected_edge_bps": float,
  "size": float,
  "reasoning": "brief explanation"
}
```

**优势**:
- 多模态输入 (数值 + 文本)
- 复杂模式识别
- 自然语言推理

## 使用示例

```python
from services.strategy_engine import StrategyEngineService
from strategies import (
    SpreadReversionStrategy,
    StatisticalArbitrageStrategy,
    KellyPositionStrategy
)

# 创建引擎
engine = StrategyEngineService()

# 注册策略
engine.register_strategy(SpreadReversionStrategy())
engine.register_strategy(StatisticalArbitrageStrategy())
engine.register_strategy(KellyPositionStrategy())

# 启动
await engine.start()

# 引擎会自动:
# 1. 订阅 FEATURE_SNAPSHOT 事件
# 2. 并发执行所有策略
# 3. 发布 SIGNAL_GENERATED 事件
```

## 信号融合 (未来扩展)

当多个策略对同一市场生成信号时,可以使用加权融合:

```python
# 示例: 加权平均
weights = {
    "spread_reversion": 0.3,
    "stat_arb": 0.4,
    "kelly_position": 0.2,
    "ai": 0.1
}

final_confidence = sum(
    signal.confidence * weights[signal.strategy_id]
    for signal in signals
)
```

## 配置参数

所有策略支持通过 `config` 字典传入参数:

```python
strategy = SpreadReversionStrategy(config={
    "lookback_window": 120,
    "entry_threshold_std": 2.5,
    "min_spread_bps": 80.0
})
```

## 性能考虑

- 策略并发执行 (asyncio.gather)
- 无状态设计 (除历史数据缓存)
- 轻量级计算 (避免复杂模型)
- 信号去重 (避免重复发送)

## 下一步

1. 实现回测框架验证策略
2. 添加参数优化工具
3. 实现信号融合算法
4. 集成实时 AI 模型
