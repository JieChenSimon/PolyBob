# PolyBob 应用性能审计

审计日期：2026-06-13  
审计范围：Next.js 前端、FastAPI API、行情与特征数据服务、回测/量化计算、本地 SQLite 事实库。  
限制：本次只做代码与构建审计，不修改生产代码；外部行情延迟尚未进行稳定网络环境下的端到端压测。

## 核心结论

1. **当前首要瓶颈是网络请求拓扑和阻塞 I/O，不是 Python 算力。** 股票页对约 100 个美股逐只请求 Nasdaq，Risk 页面每 20 秒请求 5 个接口，pair 轮询在 `async` 任务中串行执行同步 HTTP。先修这些问题，收益会明显高于直接迁移 Rust。
2. **前端已具备一部分正确优化，但缺少真实性能基线。** 已有隐藏页暂停、请求取消、轮询防重入、短 TTL 缓存和同请求合并；然而现有性能测试只测模拟 `asyncio.sleep`，不能证明真实页面、API 或数据链路达标。
3. **Rust 只适合经过 profiling 证实的 CPU 热点。** 首批候选是大规模回测循环、滚动 GARCH/协整/风险计算和高频订单簿归一化。API 编排、外部行情请求、React 渲染和 SQLite CRUD 不应为了性能改成 Rust。
4. **应按“可观测性 -> 网络/I/O -> 渲染 -> CPU -> Rust”的顺序推进。** 没有基准数据就迁 Rust，会增加构建、调试和 macOS native 扩展维护成本，却可能完全绕开真实瓶颈。

## 当前基线

2026-06-13 执行 `npm run build`：

| 路由 | 路由 JS | First Load JS |
|---|---:|---:|
| `/us-equities` | 8.68 kB | 111 kB |
| `/markets` | 10.2 kB | 215 kB |
| `/overview` | 4.21 kB | 209 kB |
| `/risk-ops` | 3.28 kB | 105 kB |
| 共享包 | - | 102 kB |

构建成功，约 2.5 秒完成编译。`/markets` 和 `/overview` 的首屏包明显高于其他页面，主要因为直接引入 Recharts；需要用 bundle analyzer 进一步确认模块占比。

当前 `tests/performance/test_latency.py` 的三个测试均以 `asyncio.sleep` 模拟处理，不调用真实 API、事件总线、特征引擎或回测引擎，因此只能验证测试调度器，不能作为性能验收依据。

## 已完成优化

| 层面 | 已有措施 | 评价 |
|---|---|---|
| 前端轮询 | `usePolling` 防止重入、使用 `AbortController`、页面隐藏时暂停并取消请求 | 正确，应统一复用 |
| 股票行情 | 只请求当前市场；前端美股 60 秒、A 股 30 秒轮询 | 降低了无关请求 |
| Next.js quote API | 单 symbol TTL 缓存、并发请求复用、每批并发 8 | 能抑制开发模式和重复访问造成的重复请求 |
| 技术指标 API | 美股 30 分钟、A 股 5 分钟缓存；同 symbol promise 合并 | 与日线数据更新频率基本匹配 |
| FastAPI 聚合接口 | overview、markets、risk、onchain、execution 使用短 TTL 缓存和单 key 锁 | 避免缓存击穿 |
| FastAPI 生命周期 | 服务和长连接在 lifespan 中初始化；交易 lab 延迟初始化 | 避免无关模块拖慢默认启动 |
| 特征计算 | 有限长度 `deque`、100ms 输出缓存、部分增量统计、Numba 风险函数 | 已避免明显的无界内存增长 |
| UI 数据量 | 市场列表上限 36/50；图表只保留最近 24 个点 | 当前规模不需要虚拟化 |

## 问题与优先级

### P0：先建立真实可观测性

| 问题 | 类型 | 证据与影响 | 建议 | Rust |
|---|---|---|---|---|
| 性能测试不覆盖真实链路 | 测量 | `tests/performance/test_latency.py` 只测固定 sleep；无法定位回归 | 增加真实 API p50/p95/p99、外部 provider 延迟、缓存命中率、事件队列延迟、React commit 时间和 Web Vitals | 否 |
| 没有请求级分段指标 | 测量 | 虽已依赖 `prometheus-client`，主 API 未暴露可见的 route/provider/cache 指标 | 为 FastAPI middleware、provider client、事件处理和回测添加 histogram/counter；区分上游等待与本地计算 | 否 |
| 没有前端性能预算 | 测量 | 只有构建输出，没有 LCP/INP/CLS、长任务或 commit 数据 | 在 production build 上采集 Lighthouse/Web Vitals；用 React Profiler 定位真实重渲染 | 否 |

### P0：消除阻塞与请求放大

| 问题 | 类型 | 证据与影响 | 建议 | Rust |
|---|---|---|---|---|
| pair 引擎在事件循环中调用同步 HTTP | 网络/I/O | `build_quote_fetcher()` 是 `async`，内部调用 `BinanceClient.get_orderbook()` 和 `HyperliquidClient.get_orderbook()`；两者使用同步 `httpx.get/post`，且左右腿串行 | 改为进程级复用的 `httpx.AsyncClient`，左右腿 `asyncio.gather`，配置连接池、总超时、重试退避和熔断 | 否 |
| pair 之间串行轮询 | 网络/I/O | `_poll_loop()` 对每个 pair 顺序 `await _build_snapshot`；pair 数增加后周期线性变长 | 对有限数量 pair 使用有界并发；记录单轮耗时，禁止上一轮未完成时叠加 | 否 |
| 股票页对约 100 个 Nasdaq symbol 逐只请求 | 网络/I/O | quote route 每 8 个一批，约 13 个串行批次；冷缓存 TTFB 由最慢上游累加 | 首选批量 provider；否则服务端后台刷新、stale-while-revalidate、按可见/收藏/选中分层加载，并设置单请求超时 | 否 |
| 外部 fetch 缺少显式超时与退避 | 网络/I/O | Next quote/technical route 依赖默认 fetch 行为；上游悬挂会拖慢整批 | 每个 provider 使用超时、有限重试、指数退避、失败缓存和 provider 健康状态；返回部分成功而非等待全量 | 否 |
| BTC WebSocket 每个前端连接每 2 秒新建 HTTP client | 网络/I/O | `/ws/market` 循环内创建 `httpx.AsyncClient` 并请求 Binance；N 个浏览器连接产生 N 份轮询 | 后端建立单个行情任务/长连接，缓存最新值并 fan-out 给所有 WebSocket 客户端 | 否 |

### P1：减少前端请求和渲染成本

| 问题 | 类型 | 证据与影响 | 建议 | Rust |
|---|---|---|---|---|
| Risk 页面每轮请求 5 个接口 | 网络/I/O | 每 20 秒 `Promise.all` risk、summary、watchlist、alerts、events；部分数据在 risk summary 中已重复聚合 | 增加专用页面聚合端点，或使用 React Query/SWR 做跨组件去重、stale time 和保留旧数据 | 否 |
| 股票 quote 每轮切换 loading | 渲染 | `fetchQuotes` 每次轮询先更新 `loading: true`，完成后再次更新；整棵股票组件至少多两次 render | 后台刷新保留旧数据，只在首次加载显示 loading；把 last-updated/fetching 与数据状态分离 | 否 |
| 股票列表每次 quote 更新重渲染约 100 行 | 渲染 | `QuoteState` 整体替换并传入 `ObservationRail`；所有行会重新执行格式化与 JSX 创建 | React Profiler 确认后拆分 memoized row，仅把该 symbol quote 传给行；必要时使用选择器状态库 | 否 |
| Recharts 进入首屏包 | 加载/渲染 | `/markets` 215 kB、`/overview` 209 kB；其他页面约 102-111 kB | 对图表组件使用 `next/dynamic` 延迟加载；lab backtest 未启用时不加载 Recharts 模块；用 bundle analyzer 设预算 | 否 |
| 页面全部以大客户端组件加载数据 | 加载 | Workspace 和股票页均为 client component，首屏等待 hydration 后才发请求 | 稳定摘要可改为 Server Component 初始数据 + 客户端增量更新；使用 route loading/streaming 改善感知速度 | 否 |
| 列表目前无虚拟化 | 渲染 | Nasdaq-100 约 100 行，当前可接受；未来扩展全市场会线性增加 DOM | 先设阈值：可见列表超过 300 行或 profiler 证明 commit 超标时再虚拟化 | 否 |

### P1：数据服务与存储

| 问题 | 类型 | 证据与影响 | 建议 | Rust |
|---|---|---|---|---|
| 新市场快照逐个串行获取 | 网络/I/O | market discovery 发布每个新市场后，realtime ingestor 立即等待 REST snapshot；初次 100 市场可能形成长串行链 | 订阅与快照解耦，使用有界 worker queue；优先高流动性市场并限制并发 | 否 |
| 事件总线无背压和队列边界 | I/O/调度 | `publish` 直接 `gather` 所有 handler；慢 handler 会阻塞上游消息接收 | 按 topic 设有界队列、消费者任务、丢弃/合并策略与 lag 指标；关键订单事件禁止丢弃 | 否 |
| trade 1 分钟指标每 tick 扫描 deque | CPU | 当前最多 100 条，成本很小；提高容量或频率后会重复扫描 | 用时间队列弹出过期项并维护 count/sum，做到摊销 O(1) | 暂不需要 |
| SQLite 每次追加都 init schema 并新建连接 | I/O | `append_audit_event()` 调用 `init_db()` 后再次 `connect()`；高频审计会增加打开连接和 DDL 检查 | 启动时 migration 一次；写入使用持久连接/专用 writer queue、批量事务、WAL 和 busy timeout | 否 |
| 内存缓存无容量上限 | 内存 | FastAPI key cache、Next quote/technical Map 不清理过期 key | 增加最大容量和定期清理；provider/symbol/limit 参数须规范化，避免高基数 key | 否 |

### P2：CPU 热点与算法

| 问题 | 类型 | 证据与影响 | 建议 | Rust |
|---|---|---|---|---|
| GARCH rolling 存在嵌套 Python 循环 | CPU | `forecast_volatility_rolling` 对每个时间点重算整个 window，复杂度约 O(n × window) | 先改算法/Numba，建立 10K/1M 样本 benchmark；仍不达标再迁 Rust | 候选 |
| rolling z-score 每个窗口重新 mean/std | CPU | `calculate_spread_zscore` 为 O(n × lookback) | rolling sum/sum-square、NumPy/Numba；验证数值稳定性 | 候选但优先级低 |
| 回测按 tick 使用 Python 对象和 dict | CPU/内存 | 每 tick 更新 dict/list，报告再构造数组；大规模多资产回放会受对象分配和 GIL 影响 | 先定义 columnar 数据契约、批量计算与真实 benchmark；保留 Python 编排 | 强候选 |
| 历史回放先完整排序并持有全部事件 | CPU/内存 | `sorted(self.events)` 产生完整副本，超大数据集会占内存 | 数据源按 timestamp 排序流式读取；Parquet 分区和批处理 | 仅核心循环可能 |
| 订单簿每条消息创建大量 Python tuple/model | CPU/内存 | 高频深度消息会频繁 JSON 解析、float 转换和 Pydantic 对象创建 | 先做采样 profiling；只保留所需档位、增量更新、批处理 | 高频下是候选 |

## Rust 适配判断

### 适合做成 `polybob_core` 的边界

保留 Python/FastAPI 负责服务编排，通过 PyO3/maturin 暴露少量批量函数：

- 多资产、百万级 bar/tick 的回测撮合循环；
- 批量 rolling volatility、GARCH forecast、Kalman hedge ratio、z-score；
- 大组合 VaR/CVaR、暴露矩阵和情景压力计算；
- 高频订单簿增量合并和微结构特征，前提是实测 Python 路径已成为 CPU 热点。

接口应优先接受 NumPy contiguous arrays/Arrow buffers，避免逐元素跨 Python-Rust 边界。必须提供纯 Python 参考实现、误差容限测试和 fallback。

### 不应迁 Rust

- Next.js/React 页面与交互；
- FastAPI route、配置、鉴权和业务编排；
- 外部免费行情请求、重试、缓存和 provider failover；
- 100 只股票的搜索、分类、收藏和简单均线；
- SQLite CRUD 和当前规模的内存状态；
- 尚未启用或没有真实数据规模的实验模块。

### Rust 启动门槛

只有同时满足以下条件才立项：

1. 真实 workload 的 profiler 证明该函数占请求/任务 CPU 时间至少 25%；
2. 算法、数据布局、NumPy/Numba 优化后仍不达验收指标；
3. 有固定数据集、正确性 oracle 和可重复 benchmark；
4. 预期端到端收益至少 2 倍，且跨语言序列化不吞掉收益；
5. CI 能构建 macOS arm64 wheel，避免再次出现 native 扩展被系统策略拒绝加载但无人维护的情况。

## 分阶段执行顺序

### Phase 0：一周内

1. 建立真实性能基线和 dashboard：API/provider/cache/event-loop/Web Vitals。
2. 修复 pair 引擎同步 HTTP、串行左右腿和 client 重建。
3. 将 BTC 行情改为单上游连接、多前端 fan-out。
4. 为所有外部 provider 增加超时、退避、失败缓存和部分成功策略。

### Phase 1：随后一至两周

1. 股票行情改成分层加载和 stale-while-revalidate，避免 100 symbol 冷启动阻塞。
2. 合并 Risk 页面请求；为前端引入统一 server-state 缓存。
3. 延迟加载 Recharts，确保 lab 关闭时不下载回测图表代码。
4. 将新市场快照改成有界 worker queue；为事件总线增加背压与 lag 指标。
5. SQLite 启动时初始化，写入走批量事务和 WAL。

### Phase 2：数据规模稳定后

1. 用真实历史数据分别 benchmark 回测、GARCH、协整、风险计算和订单簿处理。
2. 先做算法、NumPy、Numba 和数据布局优化。
3. 只把仍不达标的第一名 CPU 热点迁入 `polybob_core`，完成 A/B benchmark 后再决定第二个模块。

## 验收指标

### 前端

- production build 下 `/overview`、`/markets`、`/us-equities`：
  - LCP p75 < 2.5s；
  - INP p75 < 200ms；
  - CLS p75 < 0.1；
  - 单次交互主线程长任务 < 50ms；
  - 股票 quote 刷新 React commit p95 < 50ms。
- First Load JS：
  - 普通工作台路由 <= 130 kB；
  - 图表路由 <= 170 kB；
  - lab 关闭时 overview 不加载 Recharts。

### API 与数据服务

- 缓存命中时内部 API p95 < 50ms、p99 < 100ms。
- 不含免费上游等待的本地聚合 CPU p95 < 20ms。
- provider 请求必须有明确超时；单 provider 故障不能让整批请求超过 5s。
- quote 缓存命中率工作时段 >= 80%；同 key 并发请求合并率可观测。
- event-loop lag p99 < 50ms；事件处理队列不得无界增长。
- pair 一轮轮询完成时间 p95 < 配置周期的 50%，不得发生轮次重叠。

### CPU/Rust

- 回测基准至少覆盖 100K、1M、10M ticks，并报告 wall time、CPU time、峰值 RSS 和吞吐。
- Rust 候选必须与 Python oracle 在既定误差内一致。
- Rust 版本端到端吞吐提升 >= 2x，或 p95 延迟降低 >= 50%，才允许替换默认实现。

## 参考依据

- [Next.js Package Bundling](https://nextjs.org/docs/app/guides/package-bundling)：使用官方 bundle analyzer 定位大依赖和导入链。
- [Next.js Lazy Loading](https://nextjs.org/docs/app/guides/lazy-loading)：延迟加载 Client Component 和大型库以降低初始 JavaScript。
- [React Profiler](https://react.dev/reference/react/Profiler) 与 [React Performance Tracks](https://react.dev/reference/dev-tools/react-performance-tracks)：先测量 commit、网络、JS 和 event-loop，再决定 memoization。
- [FastAPI Concurrency and async/await](https://fastapi.tiangolo.com/async/)：`async def` 内的阻塞 I/O 不会自动移入线程池。
- [FastAPI Server Workers](https://fastapi.tiangolo.com/deployment/server-workers/)：多 worker 可利用多核，但不能代替修复单 worker 内的阻塞调用。
- [PyO3 User Guide](https://pyo3.rs/)：Rust 适合作为 Python native extension；maturin 可管理构建和打包。
