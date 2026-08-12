# Trading Strategies

PolyBob 交易策略实现 - 三个核心策略已完成实现并通过测试。

## 已实现策略

### 1. Cross Market Dislocation V1 (跨市场错位套利)

**路径**: `strategies/cross_market_dislocation_v1/`

**核心逻辑**:
- 监控所有市场对的价格差异
- 计算价差的 Z-score (标准差倍数)
- 当价差超过阈值时触发统计套利信号
- 假设价差会回归历史均值

**关键参数**:
- `z_score_threshold`: 2.0 (Z-score 阈值)
- `min_spread_bps`: 50.0 (最小价差基点)
- `lookback_window`: 100 (历史窗口)
- `signal_ttl_seconds`: 300 (信号有效期)

**信号生成**:
- Z-score > 阈值: 做空高价市场,做多低价市场
- Z-score < -阈值: 做多高价市场,做空低价市场

---

### 2. Spread Reversion V1 (价差回归策略)

**路径**: `strategies/spread_reversion_v1/`

**核心逻辑**:
- 监控单个市场的买卖价差
- 识别价差异常扩大的机会
- 在价差中间位置挂限价单做市
- 赚取价差收敛收益

**关键参数**:
- `spread_threshold_bps`: 150.0 (价差阈值基点)
- `reversion_confidence`: 0.7 (回归置信度)
- `min_depth_ratio`: 0.3 (最小深度比率)
- `signal_ttl_seconds`: 180 (信号有效期)

**信号生成**:
- 价差 > 阈值 且 订单簿平衡
- 生成双向限价单(买入和卖出)
- 在中间价 30% 位置挂单

---

### 3. AI Enhanced Prediction V1 (AI 增强预测)

**路径**: `strategies/ai_enhanced_prediction_v1/`

**核心逻辑**:
- 收集实时市场特征(价格、价差、深度、成交量)
- 使用 Claude API 分析市场问题和特征
- 生成结构化交易信号和置信度评估
- 结合量化特征和 AI 推理

**关键参数**:
- `min_confidence`: 0.6 (最小置信度)
- `signal_ttl_seconds`: 600 (信号有效期)
- `analysis_interval_seconds`: 60 (分析间隔)

**环境要求**:
```bash
ANTHROPIC_API_KEY=your_api_key_here
```

**信号生成**:
- AI 返回 BUY_YES/SELL_YES 信号
- 置信度 >= min_confidence
- 包含推理说明和预期优势

---

## 架构设计

### 事件驱动架构

所有策略通过事件总线与系统集成:

```
Feature Engine → FEATURE_SNAPSHOT → Strategies → SIGNAL_GENERATED → Risk Manager
```

### 策略接口

每个策略实现统一接口:
- `async start()`: 启动策略,订阅事件
- `async stop()`: 停止策略
- `_on_feature_snapshot()`: 处理特征更新
- `_generate_signal()`: 生成交易信号

### 信号结构

```python
Signal(
    signal_id: str,
    market_id: str,
    strategy_id: str,
    timestamp: datetime,
    side: Side,  # BUY_YES / SELL_YES
    price: float,
    size: float,
    expected_edge_bps: float,
    confidence: float,
    ttl_seconds: int,
    reason_code: str,
    explanation_ref: Optional[str]
)
```

---

## 策略管理

### Strategy Manager Service

**路径**: `modules/strategy_manager/`

统一管理所有策略的启动、停止和监控:

```python
from modules.strategy_manager import StrategyManagerService

manager = StrategyManagerService()
await manager.start()  # 启动所有策略

# 获取策略实例
strategy = manager.get_strategy("cross_market_dislocation_v1")

# 列出所有策略
strategies = manager.list_strategies()
```

---

## 测试

所有策略已通过单元测试:

```bash
uv run --locked pytest tests/test_strategies.py -v
```

测试覆盖:
- ✅ 策略初始化
- ✅ 参数配置
- ✅ 启动/停止流程
- ✅ 事件订阅

---

## 使用示例

### 单独启动策略

```python
from strategies import CrossMarketDislocationV1

config = {
    "z_score_threshold": 2.0,
    "min_spread_bps": 50.0,
}

strategy = CrossMarketDislocationV1(config)
await strategy.start()
```

### 通过 Strategy Manager 启动

```python
from modules.strategy_manager import StrategyManagerService

manager = StrategyManagerService()
await manager.start()  # 自动加载并启动所有策略
```

---

## 性能特点

### Cross Market Dislocation
- **计算复杂度**: O(n²) - 需要比较所有市场对
- **内存占用**: 中等 - 维护价差历史
- **信号频率**: 低 - 仅在显著错位时触发

### Spread Reversion
- **计算复杂度**: O(n) - 独立分析每个市场
- **内存占用**: 低 - 仅需当前特征
- **信号频率**: 中 - 价差扩大时触发

### AI Enhanced Prediction
- **计算复杂度**: O(n) - 但有 API 延迟
- **内存占用**: 低 - 缓存分析结果
- **信号频率**: 低 - 受分析间隔限制
- **成本**: 每次分析约 1K tokens

---

## 下一步

### 优化方向
1. **回测框架**: 使用历史数据验证策略表现
2. **参数优化**: 网格搜索最优参数组合
3. **风险管理**: 集成仓位管理和止损逻辑
4. **性能监控**: 实时跟踪策略 PnL 和夏普比率

### 扩展策略
1. **Momentum Strategy**: 趋势跟踪策略
2. **News Sentiment**: 新闻情绪分析策略
3. **Liquidity Provision**: 流动性提供策略
4. **Multi-leg Arbitrage**: 多腿套利策略

---

## 文件结构

```
strategies/
├── __init__.py                          # 策略模块入口
├── README.md                            # 本文档
├── cross_market_dislocation_v1/
│   ├── __init__.py
│   ├── strategy.py                      # 策略实现
│   ├── config.yaml                      # 配置文件
│   └── README.md                        # 策略文档
├── spread_reversion_v1/
│   ├── __init__.py
│   ├── strategy.py
│   ├── config.yaml
│   └── README.md
└── ai_enhanced_prediction_v1/
    ├── __init__.py
    ├── strategy.py
    ├── config.yaml
    └── README.md
```

---

## 依赖项

核心依赖已添加到 `pyproject.toml`:
- `anthropic>=0.18.0` - Claude API 客户端
- `pyyaml>=6.0` - YAML 配置解析
- `structlog>=24.1.0` - 结构化日志
- `pytest>=7.4.0` - 测试框架
- `pytest-asyncio>=0.23.0` - 异步测试支持

安装依赖:
```bash
uv sync --locked
```
