# PolyBob 项目级专业审查记录

审查日期：2026-08-24  
范围：量化研究有效性、交易执行与数据架构、产品工作流、Dashboard UX、Core/Lab/Archive 边界。  
审查方式：多 agent 并行只读审查 + 本地代码/任务/测试交叉核对。  
本轮没有修改业务代码、没有提交或回滚。

## 结论摘要

PolyBob 已具备较完整的研究工作台原型、能力边界和测试基础，但尚未形成可宣称可信的量化交易闭环。当前最重要的缺口不是 UI 数量，而是：

1. 研究结果缺少严格 PIT、真正独立 OOS 和可重放的代码/数据绑定。
2. 执行旁路、持久化降级和孤立 ExecutionLedger 使 paper/execution 状态无法作为单一事实源。
3. Dashboard 在数据不可用时仍可能显示 0、延迟或正常占位，容易把 UNKNOWN 误读成安全或没有机会。
4. Core、Lab、Archive 和多个 API/事实源仍未收敛，导致产品定位与运行状态不一致。

当前 promotion board 的安全结论是 `approved_trade=0`、`approved_avoid=1`。这表示当前没有策略被放行，不表示不存在 alpha，也不表示研究流程已经证明“没有有效策略”。

## 验证基线

- Python：`uv run --locked pytest -q` → `947 passed, 5 skipped, 10 deselected, 1 warning`。
- Dashboard：`npm test` → 17 files / 73 tests；`npm run build` 通过。
- 任务完整性：`uv run --locked python scripts/dev_control.py validate` → `OK 22 tasks`。
- 当前工作树仍包含大量未提交改动；因此历史 manifest、任务 YAML 和当前 checkout 不可自动视为同一版本。
- 默认测试没有运行 `real_data`，所以供应商连通性、真实数据新鲜度和 live execution 均不能由上述绿灯推出。

状态定义：`CONFIRMED` 表示已有代码/运行复现或静态证据；`BLOCKER` 表示相关结果不得进入交易性结论；`UNKNOWN` 表示当前没有足够证据确认或排除。

## A. 量化研究与统计有效性

### Q-001｜BLOCKER｜研究 manifest 的可复现声明没有绑定当前 checkout

- 证据：[libs/data/run_manifest.py:139](/Users/SimonChen/workspace/codespace/PolyBob/libs/data/run_manifest.py:139)、[scripts/research.py:194](/Users/SimonChen/workspace/codespace/PolyBob/scripts/research.py:194)。
- 现象：manifest 只检查自身记录的 commit/dirty 字段，没有要求当前 HEAD 与记录 commit 一致，也没有强制在对应 clean commit 重放。
- 后果：`run_reproducible=true` 不能证明当前代码可以复现结果。
- 映射：PB-0015；状态 CONFIRMED。

### Q-002｜BLOCKER｜历史 PIT 合同不足以证明信息当时可获得

- 证据：[libs/data/store.py:104](/Users/SimonChen/workspace/codespace/PolyBob/libs/data/store.py:104)、[libs/data/store.py:357](/Users/SimonChen/workspace/codespace/PolyBob/libs/data/store.py:357)、[libs/quant/event_study_board.py:454](/Users/SimonChen/workspace/codespace/PolyBob/libs/quant/event_study_board.py:454)。
- 现象：默认字段是抓取时间而非供应商实际发布时间；`as_of` 主要按 observation time 过滤，`insider_filings` 与 `corporate_actions` 当前没有可用存储证据。
- 后果：交易型历史结果的 PIT 状态只能是 UNKNOWN，不应晋级。
- 映射：PB-0014、PB-0015、PB-0016；状态 CONFIRMED/BLOCKER。

### Q-003｜BLOCKER｜内幕事件存在同日入场 lookahead 风险

- 证据：[libs/data/sec_insider.py:44](/Users/SimonChen/workspace/codespace/PolyBob/libs/data/sec_insider.py:44)、[libs/quant/edge_backtest.py:247](/Users/SimonChen/workspace/codespace/PolyBob/libs/quant/edge_backtest.py:247)、[data/insider_results.json:64](/Users/SimonChen/workspace/codespace/PolyBob/data/insider_results.json:64)。
- 现象：数据只有 filing date，没有可靠公开时刻；回测使用 signal date 当天第一根可用价格，结果中约 1,019 个事件为同日入场。
- 后果：`+3.25%`、`t=4.21` 等结果不能解释为可执行收益；必须使用下一交易日或有可信日内发布时间。
- 映射：PB-0016；状态 CONFIRMED/BLOCKER。

### Q-004｜BLOCKER｜当前 OOS 不是真正 walk-forward

- 证据：[libs/quant/event_study_board.py:228](/Users/SimonChen/workspace/codespace/PolyBob/libs/quant/event_study_board.py:228)、[scripts/insider_experiment.py:104](/Users/SimonChen/workspace/codespace/PolyBob/scripts/insider_experiment.py:104)。
- 现象：`_out_of_sample()` 只把完整事件序列切成前后两段，没有在前段重新选择参数、方向或模型，再锁定到后段。
- 后果：后半段方向未反转只能说明方向稳定性，不能称为独立 OOS 验证。
- 映射：PB-0016；状态 CONFIRMED/BLOCKER。

### Q-005｜HIGH｜聚类单位可能低估重叠持有期相关性

- 证据：[libs/quant/clustered_inference.py:48](/Users/SimonChen/workspace/codespace/PolyBob/libs/quant/clustered_inference.py:48)、[data/promotion_board.json:80](/Users/SimonChen/workspace/codespace/PolyBob/data/promotion_board.json:80)。
- 现象：当前按周/月日历桶聚类，而非按持仓区间重叠或风险暴露聚类；20 日持有期可能被拆到多个 calendar cluster。
- 后果：有效独立 cluster 数可能被高估，显著性不能直接用于晋级。当前 board 已显示部分证据 cluster 极少。
- 映射：PB-0016；状态 CONFIRMED/HIGH。

### Q-006｜HIGH｜事件覆盖缺失引入选择性样本偏差

- 证据：[scripts/insider_experiment.py:171](/Users/SimonChen/workspace/codespace/PolyBob/scripts/insider_experiment.py:171)、[libs/quant/edge_backtest.py:90](/Users/SimonChen/workspace/codespace/PolyBob/libs/quant/edge_backtest.py:90)。
- 现象：1,430 个内幕事件中约 1,370 个进入价格回放，缺失事件直接被排除，未证明缺失与可测样本可交换。
- 后果：结果不能无条件外推到全部发行人；覆盖率必须作为结果不确定性和选择机制报告。
- 映射：PB-0015、PB-0016；状态 CONFIRMED/HIGH。

### Q-007｜UNKNOWN｜旧版回测和 mock 数据脚本仍可能产出误导性“验证通过”

- 证据：[scripts/backtest_fusion.py:178](/Users/SimonChen/workspace/codespace/PolyBob/scripts/backtest_fusion.py:178)、[scripts/quick_validation.py:12](/Users/SimonChen/workspace/codespace/PolyBob/scripts/quick_validation.py:12)、[pytest.ini:17](/Users/SimonChen/workspace/codespace/PolyBob/pytest.ini:17)。
- 现象：部分路径在真实数据不足时使用 mock/生成数据；默认测试排除 `real_data`。
- 后果：`PROMOTE`、高 Sharpe 或 validation passed 不能自动解释为真实历史有效性。
- 映射：PB-0015、PB-0016；状态 UNKNOWN，必须保持 fail-closed。

## B. 执行、数据与系统架构

### X-001｜HIGH｜Basket API 绕过 intent、晋级和组合风控

- 证据：[apps/api/main.py:1385](/Users/SimonChen/workspace/codespace/PolyBob/apps/api/main.py:1385)、[modules/execution_engine/intent_execution_service.py:172](/Users/SimonChen/workspace/codespace/PolyBob/modules/execution_engine/intent_execution_service.py:172)、[modules/execution_engine/intent_execution_service.py:350](/Users/SimonChen/workspace/codespace/PolyBob/modules/execution_engine/intent_execution_service.py:350)。
- 后果：当前虽以 paper 为主，但接入 live venue 后会成为可绕过安全门的执行旁路。
- 映射：PB-0017、PB-0021；状态 CONFIRMED/HIGH。

### X-002｜HIGH｜ExecutionLedger 是孤立实现，不是生产事实源

- 证据：[libs/db/execution_ledger.py:223](/Users/SimonChen/workspace/codespace/PolyBob/libs/db/execution_ledger.py:223)、[modules/execution_engine/basket_executor.py:230](/Users/SimonChen/workspace/codespace/PolyBob/modules/execution_engine/basket_executor.py:230)。
- 现象：ledger 实现了 `apply_fill`，但生产执行路径没有调用；basket repository 只更新订单/basket 状态。
- 后果：cash、position、fee、PnL、订单状态和重启恢复不是单一事实链。
- 映射：PB-0017、PB-0018；状态 CONFIRMED/HIGH。

### X-003｜HIGH｜持久化失败后执行仍继续，属于 fail-open

- 证据：[apps/api/main.py:554](/Users/SimonChen/workspace/codespace/PolyBob/apps/api/main.py:554)、[modules/execution_engine/intent_execution_service.py:58](/Users/SimonChen/workspace/codespace/PolyBob/modules/execution_engine/intent_execution_service.py:58)。
- 后果：数据库不可用时仍可创建 paper order，重启后可能无法恢复、对账或审计。
- 映射：PB-0017；状态 CONFIRMED/HIGH。

### X-004｜HIGH｜Portfolio、Journal、ExecutionLedger 三套事实链脱节

- 证据：[apps/api/portfolio_api.py:32](/Users/SimonChen/workspace/codespace/PolyBob/apps/api/portfolio_api.py:32)、[apps/api/journal_api.py:99](/Users/SimonChen/workspace/codespace/PolyBob/apps/api/journal_api.py:99)。
- 后果：手工 Journal、执行成交和账本可能产生不同仓位、P&L 与风险结论。
- 映射：PB-0017、PB-0018；状态 CONFIRMED/HIGH。

### X-005｜HIGH｜容器/wheel 运行包缺少 config/data，且缺失时可能静默空晋级板

- 证据：[Dockerfile:22](/Users/SimonChen/workspace/codespace/PolyBob/Dockerfile:22)、[apps/api/main.py:118](/Users/SimonChen/workspace/codespace/PolyBob/apps/api/main.py:118)、[libs/quant/promotion_registry.py:128](/Users/SimonChen/workspace/codespace/PolyBob/libs/quant/promotion_registry.py:128)。
- 后果：部署后 pair/watchlist、promotion board 或 sample data 消失，并可能被误判为“没有晋级策略”。
- 映射：PB-0001；状态 CONFIRMED/HIGH。

### X-006｜HIGH｜默认关闭的 Lab simulation 仍被启动

- 证据：[libs/config.py:68](/Users/SimonChen/workspace/codespace/PolyBob/libs/config.py:68)、[apps/api/main.py:697](/Users/SimonChen/workspace/codespace/PolyBob/apps/api/main.py:697)、[modules/simulation/service.py:197](/Users/SimonChen/workspace/codespace/PolyBob/modules/simulation/service.py:197)。
- 后果：设置页显示 disabled，但后台仍注册事件和恢复 simulation 状态，Core/Lab 运行边界不诚实。
- 映射：PB-0002、PB-0021；状态 CONFIRMED/HIGH。

### X-007｜MEDIUM｜Provider HTTP 调用绕过统一 bounded client

- 证据：[libs/data/http_client.py:52](/Users/SimonChen/workspace/codespace/PolyBob/libs/data/http_client.py:52)、[libs/crypto/binance_client.py:28](/Users/SimonChen/workspace/codespace/PolyBob/libs/crypto/binance_client.py:28)、[libs/polymarket/clob_client.py:14](/Users/SimonChen/workspace/codespace/PolyBob/libs/polymarket/clob_client.py:14)。
- 后果：长期运行时连接、代理隧道和文件描述符压力不受项目统一策略控制。
- 映射：PB-0021；状态 CONFIRMED/MEDIUM。

### X-008｜MEDIUM｜启动脚本使用 npm install，破坏可重复安装

- 证据：[start-all.sh:103](/Users/SimonChen/workspace/codespace/PolyBob/start-all.sh:103)。
- 后果：已有 lockfile 时仍可能重新解析或更新依赖；与 Python 侧 `uv --locked` 的可重复性策略不一致。
- 映射：PB-0021；状态 CONFIRMED/MEDIUM。

## C. 产品设计与 Dashboard

### U-001｜HIGH｜API 不可用时 UNKNOWN 被渲染为 0

- 证据：[apps/dashboard/components/TodaysEdges.tsx:110](/Users/SimonChen/workspace/codespace/PolyBob/apps/dashboard/components/TodaysEdges.tsx:110)、[apps/dashboard/components/EdgeScoreboard.tsx:250](/Users/SimonChen/workspace/codespace/PolyBob/apps/dashboard/components/EdgeScoreboard.tsx:250)。
- 后果：用户可能把“数据故障”误解为“今天没有机会”，这是金融工作台最危险的语义错误之一。
- 映射：PB-0013、PB-0020；状态 CONFIRMED/HIGH。

### U-002｜HIGH｜Dashboard 存在两套 API 边界，健康状态互相矛盾

- 证据：[apps/dashboard/lib/config.ts:1](/Users/SimonChen/workspace/codespace/PolyBob/apps/dashboard/lib/config.ts:1)、[apps/dashboard/components/OverviewWorkspace.tsx:15](/Users/SimonChen/workspace/codespace/PolyBob/apps/dashboard/components/OverviewWorkspace.tsx:15)。
- 后果：核心 API 不可用时，股票内部路由仍可返回行情；用户无法判断哪些数据可用于决策。
- 映射：PB-0021、PB-0020；状态 CONFIRMED/HIGH。

### U-003｜HIGH｜非实时行情没有区分 delayed、last close、stale

- 证据：[apps/dashboard/app/api/us-equities/quotes/route.ts:193](/Users/SimonChen/workspace/codespace/PolyBob/apps/dashboard/app/api/us-equities/quotes/route.ts:193)、[apps/dashboard/app/api/us-equities/quotes/route.ts:474](/Users/SimonChen/workspace/codespace/PolyBob/apps/dashboard/app/api/us-equities/quotes/route.ts:474)。
- 后果：数日前的收盘数据看起来像普通延迟行情，可能被用于技术判断。
- 映射：PB-0020；状态 CONFIRMED/HIGH。

### U-004｜MEDIUM｜失败态同时显示错误、骨架屏和占位数据

- 证据：[apps/dashboard/components/OverviewWorkspace.tsx:40](/Users/SimonChen/workspace/codespace/PolyBob/apps/dashboard/components/OverviewWorkspace.tsx:40)。
- 后果：用户无法区分系统整体不可用、单模块失败和正常无数据；重试入口也被分散。
- 映射：PB-0020；状态 CONFIRMED/MEDIUM。

### U-005｜MEDIUM｜Markets 和 Crypto 页面混入跨域/Lab 工作流

- 证据：[apps/dashboard/app/markets/page.tsx:21](/Users/SimonChen/workspace/codespace/PolyBob/apps/dashboard/app/markets/page.tsx:21)、[apps/dashboard/app/crypto/page.tsx:1](/Users/SimonChen/workspace/codespace/PolyBob/apps/dashboard/app/crypto/page.tsx:1)、[apps/dashboard/components/ForecastBatchScanner.tsx:68](/Users/SimonChen/workspace/codespace/PolyBob/apps/dashboard/components/ForecastBatchScanner.tsx:68)。
- 后果：用户进入 Markets/Crypto 后不能立即得到单一操作结论，Core 与 Lab 边界依赖用户自行理解。
- 映射：PB-0013、PB-0020；状态 CONFIRMED/MEDIUM。

### U-006｜MEDIUM｜导航无障碍语义错误，Settings 中英文状态混杂

- 证据：[apps/dashboard/components/PrimaryNav.tsx:58](/Users/SimonChen/workspace/codespace/PolyBob/apps/dashboard/components/PrimaryNav.tsx:58)、[apps/dashboard/components/SettingsOverview.tsx:91](/Users/SimonChen/workspace/codespace/PolyBob/apps/dashboard/components/SettingsOverview.tsx:91)。
- 后果：辅助技术不能可靠识别导航链接；中文核心运行状态仍直接显示后端英文。
- 映射：PB-0003、PB-0020；状态 CONFIRMED/MEDIUM。

## 专业产品判断

从专业量化系统角度，当前最关键的成熟度缺口是“证据和状态的可追溯性”，而不是再增加策略、指标或页面。没有严格 PIT、独立 OOS、真实成交/对账和唯一事实源时，系统最多支持研究探索和 paper 记录，不能支持交易性结论。

从专业金融工作台角度，核心设计应围绕一条闭环：

`review -> evidence -> decision -> risk check -> paper action -> fill -> ledger -> review`

当前 Dashboard 仍以组件和页面聚合为主，缺少持久化的 `case -> decision -> action -> execution -> review` 生命周期。尤其是 `UNKNOWN -> 0`、`stale -> delayed` 和多套 API 健康状态，会直接损害操作员判断。

## 后续验收门槛

任何问题关闭前至少应满足：

1. 有最小可复现测试或运行证据，不只改文档或任务 YAML。
2. 对量化结论提供数据版本、代码 commit、PIT 时间、模型版本、参数和样本外证据。
3. 对执行结论提供 intent、order、fill、ledger、portfolio、audit 的一致链路和重启恢复证据。
4. 对 UI 失败态验证 `unknown != 0`、freshness 明确、来源/时点可见、Core/Lab 隔离。
5. 所有无法运行的 real-data、live-provider 或 external-network 检查保持 UNKNOWN。

## 第二轮复核补充

以下问题是第二轮 agent team 对代码和页面的进一步核对结果；它们不是仅凭路线图推断。

### Q-008｜CRITICAL｜存在并行且不等价的回测/成交会计

- 证据：[libs/backtest/engine.py:103](/Users/SimonChen/workspace/codespace/PolyBob/libs/backtest/engine.py:103)、[libs/backtest/engine.py:122](/Users/SimonChen/workspace/codespace/PolyBob/libs/backtest/engine.py:122)、[libs/backtest/replay.py:34](/Users/SimonChen/workspace/codespace/PolyBob/libs/backtest/replay.py:34)。
- 现象：一个引擎允许无保证金卖空、缺失价格按 0 计价；另一条 replay 历史数据加载尚未实现。
- 后果：不同入口可能产生不一致的持仓、现金和 PnL，结果不能视为同一回测内核。
- 映射：PB-0016；状态 CONFIRMED/CRITICAL。

### Q-009｜CRITICAL｜费用/滑点模型未统一到真实成交条件

- 证据：[libs/quant/edge_backtest.py:340](/Users/SimonChen/workspace/codespace/PolyBob/libs/quant/edge_backtest.py:340)、[scripts/promotion_backtest.py:174](/Users/SimonChen/workspace/codespace/PolyBob/scripts/promotion_backtest.py:174)。
- 现象：不同回测路径使用固定事件 cost bps 或换手率成本，没有统一 venue fee、盘口深度、成交拆分和真实成交校准。
- 后果：策略边际收益可能被系统性高估，不能支持容量或可交易性结论。
- 映射：PB-0016、PB-0022；状态 CONFIRMED/CRITICAL。

### Q-010｜CRITICAL｜walk-forward 没有 purge/embargo，也没有训练参数传递

- 证据：[libs/backtest/walk_forward.py:55](/Users/SimonChen/workspace/codespace/PolyBob/libs/backtest/walk_forward.py:55)、[libs/backtest/walk_forward.py:84](/Users/SimonChen/workspace/codespace/PolyBob/libs/backtest/walk_forward.py:84)、[scripts/promotion_backtest.py:177](/Users/SimonChen/workspace/codespace/PolyBob/scripts/promotion_backtest.py:177)。
- 现象：窗口切分后仍调用同一个回测函数，未在 train 上拟合/选择并锁定到 test；promotion 路径只是把已有收益切段。
- 后果：不能称为真正样本外验证，且重叠标签/持有期泄漏没有被处理。
- 映射：PB-0016；状态 CONFIRMED/CRITICAL。

### Q-011｜HIGH｜通用 PromotionGate 可在缺少成本或 OOS 时跳过检查

- 证据：[libs/quant/promotion.py:217](/Users/SimonChen/workspace/codespace/PolyBob/libs/quant/promotion.py:217)、[libs/quant/promotion.py:260](/Users/SimonChen/workspace/codespace/PolyBob/libs/quant/promotion.py:260)。
- 现象：默认 `n_trials=1`；未传入成本或 OOS 数据时，对应检查会被跳过，即使 registry 已登记大量搜索。
- 后果：不同调用方可以得到不同严格程度的晋级结论，形成 promotion gate 旁路。
- 映射：PB-0015、PB-0022；状态 CONFIRMED/HIGH。

### X-009｜HIGH｜幂等、恢复、时钟和审计仍不满足执行系统要求

- 证据：[modules/execution_engine/intent_execution_service.py:181](/Users/SimonChen/workspace/codespace/PolyBob/modules/execution_engine/intent_execution_service.py:181)、[modules/execution_engine/trade_journal.py:192](/Users/SimonChen/workspace/codespace/PolyBob/modules/execution_engine/trade_journal.py:192)、[modules/execution_engine/basket_executor.py:60](/Users/SimonChen/workspace/codespace/PolyBob/modules/execution_engine/basket_executor.py:60)、[modules/execution_engine/order_manager.py:41](/Users/SimonChen/workspace/codespace/PolyBob/modules/execution_engine/order_manager.py:41)。
- 现象：intent 先查后写没有锁；Journal 重试可能重复累计费用或覆盖状态；恢复只标记 `reconciling`；订单时间使用 naive 本地时间；审计失败只 warning。
- 后果：并发请求、重试、重启和时钟漂移可能产生重复经济动作或无法解释的审计记录。
- 映射：PB-0017、PB-0019；状态 CONFIRMED/HIGH。

### U-007｜P0｜发现结果无法在产品内创建决策/行动记录

- 证据：[apps/dashboard/components/InstrumentDetail.tsx:97](/Users/SimonChen/workspace/codespace/PolyBob/apps/dashboard/components/InstrumentDetail.tsx:97)、[apps/dashboard/components/JournalWorkspace.tsx:81](/Users/SimonChen/workspace/codespace/PolyBob/apps/dashboard/components/JournalWorkspace.tsx:81)、[apps/api/journal_api.py:52](/Users/SimonChen/workspace/codespace/PolyBob/apps/api/journal_api.py:52)。
- 现象：后端已有创建接口，但标的页只有跳转日志，Journal 页面只有查询、登记成交、平仓，没有“采取/跳过/创建行动”入口。
- 后果：`发现 -> 证据` 能走通，但 `决策 -> paper action -> 复盘` 不能在产品内落账。
- 映射：PB-0020；状态 CONFIRMED/P0。

### U-008｜P1｜能力矩阵不是可追溯的运行快照

- 证据：[apps/api/capabilities_api.py:20](/Users/SimonChen/workspace/codespace/PolyBob/apps/api/capabilities_api.py:20)、[apps/api/capabilities_api.py:156](/Users/SimonChen/workspace/codespace/PolyBob/apps/api/capabilities_api.py:156)、[apps/dashboard/components/SettingsOverview.tsx:63](/Users/SimonChen/workspace/codespace/PolyBob/apps/dashboard/components/SettingsOverview.tsx:63)。
- 现象：状态对象缺少 `observed_at`、provider、配置快照、检查结果版本和健康检查来源。
- 后果：用户无法知道 capability 状态基于何时、何配置、何次验证，也不能复盘当时的系统边界。
- 映射：PB-0013、PB-0021；状态 CONFIRMED/P1。

### U-009｜P1｜Daily Brief 没有待处理/到期/失败操作队列

- 证据：[apps/dashboard/app/overview/page.tsx:19](/Users/SimonChen/workspace/codespace/PolyBob/apps/dashboard/app/overview/page.tsx:19)、[apps/dashboard/components/JournalWorkspace.tsx:101](/Users/SimonChen/workspace/codespace/PolyBob/apps/dashboard/components/JournalWorkspace.tsx:101)。
- 后果：首页不能回答“今天要登记什么、补什么成交、处理哪个失败任务、复核哪个到期决定”。这使首页成为信息聚合页，而不是操作队列。
- 映射：PB-0020；状态 CONFIRMED/P1。

### U-010｜P1｜单标的决策页缺少证据 lineage 字段

- 证据：[apps/dashboard/components/BestOpportunity.tsx:148](/Users/SimonChen/workspace/codespace/PolyBob/apps/dashboard/components/BestOpportunity.tsx:148)、[apps/dashboard/components/InstrumentDetail.tsx:105](/Users/SimonChen/workspace/codespace/PolyBob/apps/dashboard/components/InstrumentDetail.tsx:105)。
- 现象：页面显示策略、胜率、收益、样本数和文字 evidence，但没有 source、freshness、PIT、模型版本、基线和校准状态。
- 后果：用户无法从“为什么现在做/不做”回到具体数据版本和研究条件。
- 映射：PB-0020；状态 CONFIRMED/P1。

### U-011｜P1｜Journal、BTC-5m 和部分页面继续把异常/未知转成正常值

- 证据：[apps/dashboard/components/JournalWorkspace.tsx:161](/Users/SimonChen/workspace/codespace/PolyBob/apps/dashboard/components/JournalWorkspace.tsx:161)、[apps/dashboard/components/BtcFiveMinuteWorkbenchClient.tsx:43](/Users/SimonChen/workspace/codespace/PolyBob/apps/dashboard/components/BtcFiveMinuteWorkbenchClient.tsx:43)。
- 现象：Journal 无 measured 结果时显示 `0 / 0` 或按 0 判断颜色；BTC-5m 查询未检查 `response.ok`，HTTP 500 的 JSON 可能被当成正常 unavailable payload。
- 后果：不同页面对 unknown、错误和零值使用不同语义，操作员无法建立一致判断。
- 映射：PB-0013、PB-0020、PB-0021；状态 CONFIRMED/P1。

### U-012｜P2｜Markets 缺少专业 triage 筛选，候选表交互也不完整

- 证据：[apps/dashboard/components/MarketsWorkspace.tsx:52](/Users/SimonChen/workspace/codespace/PolyBob/apps/dashboard/components/MarketsWorkspace.tsx:52)、[apps/dashboard/components/MarketList.tsx:47](/Users/SimonChen/workspace/codespace/PolyBob/apps/dashboard/components/MarketList.tsx:47)、[apps/dashboard/components/AltcoinDiscoveryWorkspace.tsx:199](/Users/SimonChen/workspace/codespace/PolyBob/apps/dashboard/components/AltcoinDiscoveryWorkspace.tsx:199)。
- 现象：主要只有关键词搜索，没有 abnormal、wide spread、流动性、临近结束、favorites 等队列筛选；候选表使用 `tr onClick`，缺乏键盘焦点和可访问语义。
- 后果：市场观察更像内容浏览，而不是高密度专业 triage 工作台。
- 映射：PB-0020；状态 CONFIRMED/P2。

### U-013｜P2｜i18n 和样例数据真实性边界不完整

- 证据：[apps/dashboard/app/us-equities/page.tsx:6](/Users/SimonChen/workspace/codespace/PolyBob/apps/dashboard/app/us-equities/page.tsx:6)、[apps/dashboard/app/polymarket/page.tsx:34](/Users/SimonChen/workspace/codespace/PolyBob/apps/dashboard/app/polymarket/page.tsx:34)、[data/sample_backtest_data.json:1](/Users/SimonChen/workspace/codespace/PolyBob/data/sample_backtest_data.json:1)。
- 现象：英文模式仍有固定中文标题；sample backtest 没有 source、real_data_only、生成方式或 manifest 标记。
- 后果：语言切换不完整，且使用者可能把样例回测误认成真实历史证据。
- 映射：PB-0020、PB-0021；状态 CONFIRMED/P2（样例是否实际被误用为真实证据仍为 UNKNOWN）。

## 第二轮结论

第二轮没有发现可以推翻前述结论的证据。相反，复核表明：量化证据阻断、执行事实源断裂和产品行动闭环缺失是相互耦合的系统性问题，而不是孤立 bug。PB-0015、PB-0016、PB-0017、PB-0020、PB-0021 仍是主路径；它们的 `todo/doing` 状态必须保持，不能仅因单元测试通过而关闭。

## 2026-08-24 修复进度

本轮已实际落地并通过回归的修复：

- PromotionGate 缺少 cost/OOS 时返回 `unknown`，不再静默跳过；cluster evidence 不足时保持 UNKNOWN。
- 默认回测禁止无保证金做空；缺失 mark price 不再按 0 计价；walk-forward 增加 purge/embargo 参数并要求训练参数隔离入口。
- API 直接 basket 提交改为明确 blocked；simulation 全部路由受 Lab 开关保护；Lab simulation 默认不启动。
- fact store 初始化失败时 API 启动失败，不再以 memory-only 继续执行。
- API 默认监听配置的 loopback host，CORS 不再全开放；provider HTTP 使用有界共享 transport，并在停机时关闭异步客户端。
- Docker/wheel 运行包纳入 `config/` 和 `data/`；启动脚本使用 `npm ci`。
- Dashboard freshness 明确区分 realtime/delayed/stale/last close/unknown；错误响应检查 `response.ok`；Journal 增加行动记录入口；多个未知数值不再回退为 0；主导航移除错误的 `listitem` 角色。
- 修复默认测试触碰 Hyperliquid 真实网络的问题，测试改为在 transport seam 注入失败。
- Intent create/submit 增加进程内并发锁；Journal fill/close/abandon 增加不可逆状态保护，重复费用和历史状态覆盖会被拒绝并由 API 返回 409。
- Intent/Basket 持久化写失败改为 fail-closed；Paper Execution API 默认关闭时提交路由返回结构化 Lab disabled，执行台不再展示必然失败的直接 Basket 按钮或用 0 伪装未知计数。

回归结果：

- Python：`952 passed, 5 skipped, 10 deselected, 1 warning`（后续目标回归另有 14 passed）。
- Dashboard：`73 passed`，`npm run build` 通过。
- Development Control：`OK 22 tasks`；没有绕过任务状态机，也没有自动提交。

仍未完成、不能宣称已解决的边界（这些是跨进程、真实外部数据或尚未实现的产品能力，不能用单测通过替代）：

- `ExecutionLedger` 尚未完整接入 BasketExecutor 的 canonical fill/orchestration，Portfolio/Journal/ledger 仍需统一事实源。
- intent 创建/submit 的跨进程原子幂等、外部 venue 下单后的查询恢复、完整 reconcile queue 和真实 venue execution evidence 尚未完成。
- 真正历史 PIT、真实数据供应商验证、独立 walk-forward 产物和 Kronos 相对 naive baseline 的 OOS 证据尚未产生。
- Daily Brief 待处理/到期/失败队列、单标的 source/PIT/model/baseline lineage、Core/Lab 路由收敛和完整 Dashboard 无障碍尚未完成。
- Compose 的生产凭据、镜像版本和真实网络暴露仍需部署环境验证；live provider 状态继续保持 UNKNOWN。

本轮新增核对结论：

- 单进程并发幂等和 Journal 状态一致性已验证；跨进程数据库原子幂等、外部 venue 下单后的查询恢复、canonical fill ledger 接入仍未完成。
- Paper Execution 的默认边界已收紧，但未宣称已经具备真实 Paper Broker 的撮合、部分成交、费用、cancel race 和组合 NAV 能力；该结论仍由 PB-0018 承担。
- 量化 real-data/PIT/OOS/供应商证据没有因代码回归而自动变成 PASS，仍保持 UNKNOWN/BLOCKED。

## 2026-08-24 专业工作台改版第一阶段

基于 Hyperliquid、IBKR TWS、Coinbase Advanced 的官方资料和五角色 agent team 复核，已完成第一阶段 UI/UX 垂直切片：

- 主导航收敛为 Daily Brief、Markets、Equities、Strategies、Execution、Risk Ops、Settings；旧专用入口保留兼容，不再与 Core 主路径争夺层级。
- 新增 `/strategies`、`/execution`、`/risk-ops` 和 `/equities` 路由；已有策略、执行、风险组件正式可达。
- 新增统一 Workbench Chrome：页面职责标题、Core/Lab/Archive 标签、运行能力状态条、选中工作区导航。
- Daily Brief、Markets、Equities 统一页面契约；执行/API 不可用时明确显示 UNKNOWN，不再写“占位数值”。
- 增加浏览器桌面和 390px 移动 smoke：核心路由无 404、无应用错误、无横向溢出。
- 增加文档语言同步，英文切换不会继续把 `html lang` 固定为中文。

阶段验收：Python `952 passed, 5 skipped, 10 deselected, 1 warning`；Dashboard `74 passed`；`npm run build` 通过；Development Control `OK 22 tasks`。提交为 `a1b7ea6`，已推送 `pb-0012-kronos`。

尚未完成的下一阶段仍包括：统一 typed read models 和 DataTrustBar、Daily Brief 待处理队列、Markets 选中标的联动、ExecutionLedger canonical 接入、PIT/OOS 真实证据、真实 Paper Broker、Worker/checkpoint 和完整视觉回归基线。
