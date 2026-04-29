# PolyBob 测试评估框架

## 1. 测试架构概览

### 1.1 测试层级
```
tests/
├── unit/              # 单元测试 (隔离组件)
├── integration/       # 集成测试 (服务交互)
├── backtest/          # 回测验证 (历史数据)
├── performance/       # 性能测试 (延迟/吞吐)
└── stress/            # 压力测试 (极端场景)
```

### 1.2 测试覆盖率目标
- **单元测试**: ≥85% 代码覆盖率
- **集成测试**: 覆盖所有关键服务交互路径
- **回测验证**: 至少3年历史数据，多市场条件
- **性能测试**: P95延迟 <100ms, P99 <200ms
- **压力测试**: 覆盖5种极端市场场景

---

## 2. 策略回测验证方法

### 2.1 防止过拟合 (Overfitting Prevention)

#### 数据分割策略
```
训练集 (60%): 2023-01 ~ 2024-06
验证集 (20%): 2024-07 ~ 2024-12
测试集 (20%): 2025-01 ~ 2025-12
```

#### 关键验证指标
- **样本外夏普比率**: 训练集 vs 测试集差异 <30%
- **参数敏感性**: 参数±20%变化时，夏普比率下降 <40%
- **交易频率**: 避免过度交易 (日均 <10笔)
- **最大回撤一致性**: 测试集回撤不超过训练集1.5倍

### 2.2 防止前视偏差 (Look-Ahead Bias)

#### 严格时间序列规则
1. **特征计算**: 仅使用t时刻之前的数据
2. **订单执行**: 使用t+1时刻的价格 (考虑滑点)
3. **市场数据**: 禁止使用未来信息 (如收盘价预测开盘)
4. **事件驱动**: 严格按时间戳顺序处理事件

#### 代码审查检查点
```python
# ❌ 错误: 使用未来数据
df['signal'] = df['close'].shift(-1) > df['close']

# ✅ 正确: 仅使用历史数据
df['signal'] = df['close'].shift(1) > df['close'].shift(2)
```

### 2.3 交易成本建模
- **手续费**: 0.2% (Polymarket标准)
- **滑点模型**:
  - 小单 (<$1000): 0.1%
  - 中单 ($1000-$5000): 0.2%
  - 大单 (>$5000): 0.3%
- **市场冲击**: 按订单簿深度动态计算

---

## 3. Walk-Forward 分析框架

### 3.1 滚动窗口设计
```
训练窗口: 180天
测试窗口: 30天
步进间隔: 30天

示例:
- Round 1: Train[2023-01~2023-06] → Test[2023-07]
- Round 2: Train[2023-02~2023-07] → Test[2023-08]
- Round 3: Train[2023-03~2023-08] → Test[2023-09]
...
```

### 3.2 评估指标
- **稳定性**: 各测试窗口夏普比率标准差 <0.5
- **一致性**: 盈利窗口占比 >70%
- **适应性**: 不同市场环境下表现差异 <50%

### 3.3 实现要点
```python
class WalkForwardAnalyzer:
    def __init__(self, train_days=180, test_days=30, step_days=30):
        self.train_days = train_days
        self.test_days = test_days
        self.step_days = step_days

    def run(self, data, strategy):
        results = []
        for window in self.generate_windows(data):
            train_data = window['train']
            test_data = window['test']

            # 训练策略参数
            params = strategy.optimize(train_data)

            # 测试集验证
            perf = strategy.backtest(test_data, params)
            results.append(perf)

        return self.aggregate_results(results)
```

---

## 4. 性能基准测试 (Latency Profiling)

### 4.1 延迟目标
| 组件 | P50 | P95 | P99 |
|------|-----|-----|-----|
| 数据接收 | <5ms | <10ms | <20ms |
| 特征计算 | <10ms | <30ms | <50ms |
| 策略决策 | <20ms | <50ms | <100ms |
| 订单提交 | <10ms | <30ms | <50ms |
| **端到端** | **<50ms** | **<100ms** | **<200ms** |

### 4.2 测试方法
```python
@pytest.mark.performance
async def test_component_latency():
    tracker = LatencyTracker()

    for _ in range(10000):  # 大样本测试
        start = time.perf_counter()
        await component.process(data)
        latency_ms = (time.perf_counter() - start) * 1000
        tracker.record(latency_ms)

    assert tracker.p95() < TARGET_P95
    assert tracker.p99() < TARGET_P99
```

### 4.3 性能分析工具
- **cProfile**: Python性能分析
- **py-spy**: 实时采样分析
- **Prometheus**: 生产环境监控

---

## 5. 关键测试场景

### 5.1 单元测试场景
- **策略逻辑**: 信号生成、仓位计算、止损止盈
- **风控规则**: 仓位限制、回撤保护、资金检查
- **特征工程**: 技术指标、统计特征、市场微观结构
- **数学模型**: GARCH波动率、Kelly仓位、协整检验

### 5.2 集成测试场景
- **事件流**: 市场数据 → 特征 → 策略 → 订单
- **服务交互**: EventBus、Redis缓存、数据库持久化
- **错误恢复**: 网络中断、API限流、数据异常

### 5.3 回测场景
- **牛市**: 2023年Q1 (BTC上涨)
- **熊市**: 2022年Q2 (加密崩盘)
- **震荡市**: 2024年全年
- **黑天鹅**: 2020年3月 (COVID暴跌)
- **低波动**: 2019年夏季

### 5.4 压力测试场景
- **高频数据**: 1000条/秒市场更新
- **订单簿深度不足**: 流动性枯竭
- **价格跳空**: ±20%瞬间波动
- **系统过载**: CPU 90%+, 内存不足
- **网络延迟**: 500ms+ API响应

---

## 6. 持续评估与监控

### 6.1 实时监控指标
```python
# 策略健康度指标
MONITORING_METRICS = {
    "sharpe_ratio_30d": ">1.5",      # 30天滚动夏普
    "max_drawdown_30d": "<15%",      # 30天最大回撤
    "win_rate": ">55%",              # 胜率
    "profit_factor": ">1.8",         # 盈亏比
    "daily_trades": "5-20",          # 日均交易次数
    "avg_holding_time": "2-48h",     # 平均持仓时间
}
```

### 6.2 预警机制
- **性能衰退**: 夏普比率连续7天 <1.0
- **异常回撤**: 单日回撤 >5%
- **交易异常**: 日交易次数 >50 或 =0
- **延迟超标**: P95延迟连续1小时 >150ms

### 6.3 A/B测试框架
```python
class ABTestRunner:
    def run_parallel(self, strategy_a, strategy_b, duration_days=30):
        """并行运行两个策略版本"""
        results_a = self.run_strategy(strategy_a, capital=5000)
        results_b = self.run_strategy(strategy_b, capital=5000)

        return self.compare_performance(results_a, results_b)
```

---

## 7. 测试执行计划

### 7.1 开发阶段
```bash
# 快速单元测试 (每次提交)
pytest tests/unit/ -v --cov

# 集成测试 (每日)
pytest tests/integration/ -v

# 完整测试套件 (每周)
pytest tests/ -v --cov --cov-report=html
```

### 7.2 部署前验证
```bash
# 1. 回测验证 (3年数据)
python scripts/run_backtest.py --start=2023-01-01 --end=2025-12-31

# 2. Walk-forward分析
python scripts/walk_forward.py --windows=24

# 3. 性能基准测试
pytest tests/performance/ -v --benchmark

# 4. 压力测试
pytest tests/stress/ -v
```

### 7.3 生产监控
- **实时指标**: Prometheus + Grafana
- **日报**: 每日策略表现报告
- **周报**: Walk-forward滚动验证
- **月报**: 完整回测 + 参数重优化

---

## 8. 测试数据管理

### 8.1 历史数据要求
- **时间跨度**: 至少3年 (2023-2025)
- **数据频率**: 分钟级OHLCV + 订单簿快照
- **市场覆盖**: 至少20个活跃市场
- **数据质量**: 缺失率 <1%, 异常值已清洗

### 8.2 合成数据生成
```python
class SyntheticDataGenerator:
    """生成压力测试用合成数据"""

    def generate_extreme_volatility(self):
        """生成极端波动场景"""
        pass

    def generate_liquidity_crisis(self):
        """生成流动性危机场景"""
        pass
```

---

## 9. 测试覆盖率检查清单

### 9.1 代码覆盖
- [ ] 策略核心逻辑 >90%
- [ ] 风控模块 >95%
- [ ] 特征工程 >85%
- [ ] 事件处理 >80%

### 9.2 场景覆盖
- [ ] 正常市场条件
- [ ] 极端波动
- [ ] 流动性不足
- [ ] 系统故障恢复
- [ ] 并发竞争条件

### 9.3 边界条件
- [ ] 零仓位
- [ ] 满仓
- [ ] 资金不足
- [ ] 订单簿为空
- [ ] 价格为0或1

---

## 10. 下一步行动

1. **补充单元测试**: 策略逻辑覆盖率提升至90%
2. **实现Walk-forward**: 创建滚动窗口分析工具
3. **性能基准**: 建立延迟监控基线
4. **压力测试**: 实现5种极端场景测试
5. **CI/CD集成**: 自动化测试流水线
