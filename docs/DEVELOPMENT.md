# PolyBob 开发指南

## 快速开始

### 1. 环境准备

```bash
# 克隆项目
cd PolyBob

# 使用 conda 创建环境
conda env create -f environment.yml

# 激活环境
conda activate polybob
```

### 2. 配置环境

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env，填入必要配置
# 注意：Polymarket API 密钥是可选的，用于私有数据访问
```

### 3. 启动服务

```bash
# 方式1：使用启动脚本
./start.sh

# 方式2：直接运行
python -m apps.api.main
```

服务启动后访问：
- API: http://localhost:8000
- Swagger 文档: http://localhost:8000/docs

## 架构概览

### 事件驱动架构

系统采用事件驱动架构，所有模块通过事件总线通信：

```python
from libs.events import get_event_bus, Topics

# 订阅事件
event_bus = get_event_bus()
await event_bus.subscribe(Topics.MARKET_DISCOVERED, handler)

# 发布事件
await event_bus.publish(Topics.MARKET_DISCOVERED, data)
```

### 核心服务

1. **MarketDiscoveryService** - 市场发现
   - 定期扫描 Polymarket 市场
   - 维护 watchlist
   - 发布市场发现事件

2. **RealtimeIngestorService** - 实时数据采集
   - WebSocket 连接管理
   - 订单簿和成交数据采集
   - 自动重连和快照补拉

3. **FeatureEngineService** - 特征引擎
   - 实时计算市场特征
   - 异常检测和告警
   - 定期发布特征快照

## 添加新服务

### 1. 创建服务目录

```bash
mkdir -p services/my_service
```

### 2. 实现服务类

```python
# services/my_service/service.py
import structlog
from libs.events import get_event_bus, Topics

logger = structlog.get_logger()

class MyService:
    def __init__(self):
        self.event_bus = get_event_bus()
        self._running = False

    async def start(self):
        logger.info("starting_my_service")
        self._running = True

        # 订阅事件
        await self.event_bus.subscribe(Topics.SOME_EVENT, self._handler)

    async def stop(self):
        logger.info("stopping_my_service")
        self._running = False

    async def _handler(self, data):
        # 处理事件
        pass
```

### 3. 注册到主应用

```python
# apps/api/main.py
from services.my_service import MyService

my_service: MyService | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global my_service

    # 启动
    my_service = MyService()
    await my_service.start()

    yield

    # 停止
    if my_service:
        await my_service.stop()
```

## 添加新策略

### 1. 创建策略目录

```bash
mkdir -p strategies/my_strategy_v1
```

### 2. 实现策略类

```python
# strategies/my_strategy_v1/strategy.py
from libs.schemas import Signal, Side
from libs.events import get_event_bus, Topics

class MyStrategy:
    def __init__(self):
        self.event_bus = get_event_bus()

    async def start(self):
        # 订阅特征快照
        await self.event_bus.subscribe(
            Topics.FEATURE_SNAPSHOT,
            self._on_feature_snapshot
        )

    async def _on_feature_snapshot(self, features: dict):
        # 分析特征，生成信号
        if self._should_trade(features):
            signal = Signal(
                signal_id=f"sig_{timestamp}",
                market_id=features["market_id"],
                strategy_id="my_strategy_v1",
                timestamp=datetime.utcnow(),
                side=Side.BUY_YES,
                price=features["mid_price"],
                size=100,
                expected_edge_bps=50,
                confidence=0.8,
                ttl_seconds=30,
                reason_code="my_reason",
            )

            # 发布信号
            await self.event_bus.publish(Topics.SIGNAL_GENERATED, signal)

    def _should_trade(self, features: dict) -> bool:
        # 策略逻辑
        return features["spread_bps"] > 100
```

## 测试

### 运行测试

```bash
# 运行所有测试
pytest

# 运行特定测试
pytest tests/test_events.py

# 查看覆盖率
pytest --cov=libs --cov=services
```

### 编写测试

```python
# tests/test_my_service.py
import pytest
from services.my_service import MyService

@pytest.mark.asyncio
async def test_my_service():
    service = MyService()
    await service.start()

    # 测试逻辑

    await service.stop()
```

## 代码规范

### 格式化

```bash
# 格式化代码
black .

# 检查代码风格
ruff check .

# 类型检查
mypy .
```

### 日志规范

使用 structlog 记录结构化日志：

```python
import structlog

logger = structlog.get_logger()

# 记录信息
logger.info("event_occurred", key1="value1", key2="value2")

# 记录错误
logger.error("error_occurred", error=str(e), exc_info=True)
```

## 调试技巧

### 1. 查看事件流

在任何服务中添加事件监听器：

```python
async def debug_handler(data):
    print(f"Event: {data}")

await event_bus.subscribe(Topics.ORDERBOOK_TICK, debug_handler)
```

### 2. 查看特征

访问 API 端点：

```bash
curl http://localhost:8000/markets/{market_id}/features
```

### 3. 查看 Watchlist

```bash
curl http://localhost:8000/markets/watchlist
```

## 下一步开发

### Phase 1 待完成

1. **数据库集成**
   - 创建 `libs/db/` 模块
   - 实现 Postgres 和 TimescaleDB 连接
   - 创建数据表和迁移脚本

2. **监控看板**
   - 创建 `apps/dashboard/` 前端
   - 实现市场监控页面
   - 实现特征可视化

3. **告警系统**
   - 实现告警规则引擎
   - 集成通知渠道（邮件、Slack等）

### Phase 2 计划

1. **策略引擎**
   - 实现策略管理器
   - 支持多策略并行
   - 策略回测框架

2. **风控引擎**
   - 实现风控规则
   - 仓位管理
   - 熔断机制

3. **执行引擎**
   - 订单管理
   - 状态同步
   - 幂等性保证

## 常见问题

### Q: WebSocket 连接失败？

A: 检查 Polymarket WebSocket URL 是否正确，网络是否可达。

### Q: 如何添加新的事件类型？

A: 在 `libs/events/__init__.py` 的 `Topics` 类中添加新常量。

### Q: 如何持久化数据？

A: 当前版本使用内存存储，Phase 1 完成后将集成数据库。

## 参考资料

- [设计文档](docs/polymarket-realtime-ai-trading-system.md)
- [补充设计](docs/system-design-supplement.md)
- [Polymarket API 文档](https://docs.polymarket.com/)
