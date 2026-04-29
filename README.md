# PolyBob

PolyBob 是一个个人市场研究与 paper execution 工作台，面向 Polymarket 与相关 crypto / onchain 信号的日常观察、策略实验、风险复核和复盘。

它不是对外 SaaS，也不默认承诺全自动交易。默认运行路径只启动核心工作台能力；BTC demo auto trader、RL optimizer 等实验能力归入 lab，需要显式开启。

## Operating Model

PolyBob 按三层维护：

- **core**：每天可以稳定打开使用的能力，包括市场发现、实时采集、特征聚合、策略目录、intent、paper basket、风险摘要和 dashboard。
- **lab**：实验模块，可以快速试想法，但不进入默认启动路径。当前包括 BTC auto trader、RL optimizer、旧 API server 等。
- **archive**：历史方案、报告和草稿，保留上下文，但不作为当前运行路径。

## Quick Start

默认 Python 环境是 conda 中的 `polybob`。

```bash
conda env create -f environment.yml
conda activate polybob
python -m pip install -e '.[dev]'
```

配置环境变量：

```bash
cp .env.example .env
```

启动 API：

```bash
python -m apps.api.main
```

启动 dashboard：

```bash
cd apps/dashboard
npm install
npm run dev
```

默认地址：

- API: http://localhost:8000
- API Docs: http://localhost:8000/docs
- Dashboard: http://localhost:3001

## Core Path

当前核心路径：

1. `MarketDiscoveryService` 扫描 Polymarket 市场并维护 watchlist。
2. `RealtimeIngestorService` 订阅 CLOB 数据并发布 orderbook / trade 事件。
3. `FeatureEngineService` 聚合 mid price、spread、depth imbalance、volume、price jump。
4. `StrategyManagerService` 加载策略模板与实例。
5. `IntentExecutionService` 将策略或手动判断转成 trade intent。
6. `BasketExecutor` 维护多腿 paper basket。
7. `Risk & Ops` 汇总风险、onchain 告警和服务状态。

Dashboard 首页是 Daily Brief：先回答今天该看什么、哪些信号需要复核、风险有没有异常。

## Lab Modules

BTC demo auto trader 默认关闭。需要实验时显式开启：

```bash
ENABLE_LAB_AUTO_TRADER=true python -m apps.api.main
```

关闭时：

- `/api/trading/status` 返回 lab disabled 状态；
- `/api/trading/start` 返回 403；
- overview / risk 不会初始化 demo 引擎，也不会为 demo 拉取 Binance 报价。

## Project Structure

```text
apps/
  api/                  FastAPI core entrypoint
  dashboard/            Next.js personal workbench
services/
  market_discovery/     Polymarket market discovery
  realtime_ingestor/    CLOB realtime ingestion
  feature_engine/       Market feature aggregation
  strategy_manager/     Strategy templates and instances
  execution_engine/     Intent and basket execution skeleton
  risk_manager/         Risk checks
  onchain_monitor/      Normalized onchain event monitor
  auto_trader/          Lab BTC demo path
  rl_optimizer/         Lab RL optimizer path
libs/
  polymarket/           Polymarket REST / WebSocket clients
  crypto/               Binance / Hyperliquid clients
  events/               In-memory event bus
  schemas/              Shared pydantic models
  backtest/             Backtest utilities
strategies/             Strategy implementations and configs
config/                 Pair universe and onchain watchlists
.ai/memory/             Project memory and product positioning
```

## Validation

```bash
conda run -n polybob python -m pytest -q
cd apps/dashboard && npm run build
```

Current expected result:

```text
84 passed
```
