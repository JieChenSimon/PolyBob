# PolyBob

Polymarket 实时分析与交易自动化系统

## 项目结构

```
polybob/
├── apps/                    # 应用层
│   ├── api/                # FastAPI 服务
│   ├── dashboard/          # 前端看板
│   └── worker/             # 后台任务
├── services/               # 核心服务
│   ├── market_discovery/   # 市场发现
│   ├── realtime_ingestor/  # 实时数据采集
│   ├── feature_engine/     # 特征引擎
│   ├── strategy_engine/    # 策略引擎
│   ├── risk_manager/       # 风控管理
│   ├── execution_engine/   # 执行引擎
│   └── ai_orchestrator/    # AI 编排
├── strategies/             # 策略实现
├── libs/                   # 共享库
│   ├── polymarket/         # Polymarket 客户端
│   ├── events/             # 事件总线
│   ├── db/                 # 数据库
│   ├── schemas/            # 数据模型
│   └── config.py           # 配置管理
├── infra/                  # 基础设施
└── docs/                   # 文档
```

## 快速开始

### 1. 安装依赖

```bash
# 使用 conda 创建环境
conda env create -f environment.yml

# 激活环境
conda activate polybob
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，填入必要的配置
```

### 3. 启动服务

```bash
# 启动 API 服务
python -m apps.api.main
```

服务将在 http://localhost:8000 启动

### 4. 启动界面（可选）

#### Web Dashboard（推荐）

```bash
cd apps/dashboard
npm install
npm run dev
```

访问 http://localhost:3001

#### TUI（终端界面）

```bash
python -m apps.tui
```

详见 [界面使用指南](docs/UI_GUIDE.md)

### 5. 访问 API 文档

打开浏览器访问：
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 当前实现状态

### Phase 1: 数据底座（已完成）

- ✅ 项目骨架和配置管理
- ✅ 事件总线系统
- ✅ Polymarket 客户端（REST + WebSocket）
- ✅ 市场发现服务
- ✅ 实时数据采集服务
- ✅ 特征引擎服务
- ✅ 基础 API 接口
- ✅ **Web Dashboard**（赛博朋克终端风格）
- ✅ **TUI 终端界面**

### Phase 1: 待完成

- ⏳ 数据库集成（Postgres + TimescaleDB）
- ⏳ 监控看板前端
- ⏳ 告警系统
- ⏳ 日志和指标收集

### Phase 2: 策略与半自动交易（计划中）

- ⏳ 策略引擎
- ⏳ 风控引擎
- ⏳ 执行引擎
- ⏳ AI 协作层

## API 端点

### 健康检查
```
GET /
```

### 获取 Watchlist
```
GET /markets/watchlist
```

### 获取市场特征
```
GET /markets/{market_id}/features
```

## 架构设计

系统采用六层架构：

1. **数据层**：市场发现、实时采集、状态存储
2. **信号层**：特征引擎、策略引擎
3. **执行层**：订单执行、状态管理
4. **风控层**：风险检查、熔断控制
5. **AI 协作层**：研究、复盘、代码生成
6. **运维层**：监控、告警、部署

详细设计文档见 `docs/` 目录。

## 开发指南

### 运行测试

```bash
pytest
```

### 代码格式化

```bash
black .
ruff check .
```

### 类型检查

```bash
mypy .
```

## 许可证

MIT
