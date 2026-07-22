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

美股报价默认使用多源并行模式：Nasdaq 与 Finnhub 同时请求；配置 Alpaca 凭证后也会并行加入 Alpaca IEX。把 Finnhub token 写入根目录 `.env`：

```bash
FINNHUB_API_KEY=your_finnhub_token
POLYBOB_US_EQUITY_QUOTE_PROVIDER=multi
POLYBOB_FINNHUB_REQUESTS_PER_MINUTE=55
```

`start-all.sh` 和 `start-dashboard.sh` 会加载该文件。接口保留每个来源的报价状态，按新鲜度选出主报价，并计算有效来源数量与源间最大价差；单个来源失败不会阻止其他来源继续返回。

股票页的“盘口线索”不伪造订单簿。A 股使用 Eastmoney/AkShare 同源的真实五档盘口字段；如果真实五档请求失败，就显示盘口不可用，不用买一卖一或 K 线拼假盘口。这个路径不需要像 Futu OpenD 那样长期运行本地服务。

```bash
conda activate polybob
python -m pip install akshare
```

如需让 dashboard 明确使用某个 Python：

```bash
POLYBOB_AKSHARE_PYTHON=/path/to/python
```

美股没有 IBKR 账号时，盘口接口会明确返回 quote-only，不会拼假订单簿。

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

或者在项目根目录一行启动 dashboard：

```bash
./start-dashboard.sh
```

默认地址：

- API: http://localhost:18000
- API Docs: http://localhost:18000/docs
- Dashboard: http://localhost:13001

端口都可以在启动命令前覆盖：

```bash
POLYBOB_API_PORT=28000 POLYBOB_DASHBOARD_PORT=23001 ./start-all.sh
```

如果端口已被其他程序占用，启动脚本会显示占用进程并退出，不会终止其他程序。

## Core Path

当前核心路径：

1. `MarketDiscoveryService` 扫描 Polymarket 市场并维护 watchlist。
2. `RealtimeIngestorService` 订阅 CLOB 数据并发布 orderbook / trade 事件。
3. `FeatureEngineService` 聚合 mid price、spread、depth imbalance、volume、price jump。
4. `StrategyManagerService` 加载策略模板与实例。
5. `IntentExecutionService` 将策略或手动判断转成 trade intent。
6. `BasketExecutor` 维护多腿 paper basket。
7. `Risk Ops` 汇总风险、onchain 告警和服务状态。

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
- 如果真实 portfolio ledger 尚未配置，overview / risk 返回 `portfolio_status: not_configured`，并将 exposure / leverage / PnL 保持为 unknown，而不是回退为 0。
- `services/api_server` 是 archive 入口，不再提供可运行交易 API；当前 API 入口是 `python -m apps.api.main`。

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
  db/                   Local SQLite fact store skeleton
  schemas/              Shared pydantic models
  backtest/             Backtest utilities
strategies/             Strategy implementations and configs
config/                 Pair universe and onchain watchlists
.ai/memory/             Project memory and product positioning
```

## Local Fact Store

PolyBob includes a minimal local SQLite fact-store skeleton for paper research records.
The default database path is `./.polybob/polybob.sqlite3` and can be overridden with
`POLYBOB_DB_PATH`.

The current helper module is `libs.db`:

- `init_db()` / `bootstrap()` creates the minimal tables.
- `connect()` opens a SQLite connection with foreign keys enabled.
- `append_audit_event()` records durable audit events.

This store is not connected to the API startup path yet.

## Validation

```bash
conda run -n polybob python -m pytest -q
cd apps/dashboard && npm run build
```

Current expected result:

```text
84 passed
```
