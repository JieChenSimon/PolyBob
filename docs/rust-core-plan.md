# PolyBob 渐进式 Rust Core 架构方案

## 核心结论

1. **不重写 PolyBob，也不把 Rust 当作默认答案。** Python/FastAPI 继续负责业务编排、数据源接入、策略组合、配置和可观测性；Next.js 继续负责前端。Rust 只承接经 profiling 证明的 CPU 密集型纯计算。
2. **v1 已落地配对量化、批量风险指标与回测滑点数值内核。** 当前 `rust/polybob-core` 暴露 `rolling_zscore`、`kalman_hedge_ratio`、`risk_metrics`、`max_drawdown` 和 `slippage_batch`，Python 侧由 `libs.compute` 统一选择后端。
3. **任何迁移都必须通过三重门禁：正确性、性能、可运维性。** 没有代表性数据集、Python 基线、交叉实现测试和稳定 fallback，不进入生产路径。
4. **PyO3/maturin 只暴露少量粗粒度批处理 API。** 禁止逐 tick 跨 FFI 调用；输入优先使用连续 NumPy 数组，输出使用标量、固定结构或 NumPy 数组。
5. **Python 实现长期保留为参考实现和故障回退。** Rust 出现导入失败、不支持平台、校验失败或运行错误时，系统必须能显式回退，且不得悄悄改变计算语义。
6. **网络行情、免费数据源延迟、React 渲染、数据库访问等 I/O 瓶颈不能靠 Rust 解决。** 这些模块应使用缓存、批量请求、并发控制、分页/虚拟化和查询优化。

## 目标与非目标

### 目标

- 降低大规模历史回测、风险指标批量计算和事件回放的 CPU 时间。
- 降低计算密集任务的尾延迟，并允许 Python API 服务保持响应。
- 建立可复现、可比较的性能基线，避免凭语言偏好进行重写。
- 保持当前 Python 调用方稳定，让迁移能够逐模块启用和撤回。
- 为未来 Parquet/Arrow 历史数据扫描和订单簿特征计算预留边界。

### 非目标

- 不用 Rust 重写 FastAPI、数据源适配器、SQLite 事实库或 Next.js。
- 不在第一阶段重写 SciPy 优化器。
- 不改变交易、风险或回测公式。
- 不以 Rust 迁移代替数据真实性、数据质量和时间一致性治理。
- 不将实验性内核直接接入真实执行路径。

## 当前代码映射

| 当前模块 | 特征 | Rust 适配度 | 决策 |
| --- | --- | --- | --- |
| `libs/quant/risk_metrics.py` | 连续数值数组、VaR/CVaR、回撤、比率 | 高 | 第一批候选 |
| `libs/backtest/engine.py` | 权益曲线、滑点、持仓更新、Numba | 中高 | 先迁纯数值核，再评估状态机 |
| `libs/backtest/metrics.py` | 简单线性扫描 | 中 | 与风险指标合并批量测试 |
| `libs/backtest/replay.py` | 排序、异步等待、事件发布 | 低至中 | 仅在百万级事件排序/解码成为热点后迁移 |
| `libs/backtest/execution.py` | 少量数学、异步模拟延迟 | 低 | 保留 Python |
| `libs/quant/portfolio_optimization.py` | SciPy SLSQP、矩阵求逆 | 中低 | 先优化数据与调用频率，不首迁 |
| `modules/risk_manager/*` | 业务规则与状态 | 低 | 保留 Python |
| 行情 API、缓存、数据库 | I/O 密集 | 低 | 不迁 Rust |
| Dashboard | React 渲染与网络请求 | 无 | 不迁 Rust |

## 当前实现目录

当前已经使用独立但同仓库的 Python 扩展包：

```text
rust/
  polybob-core/
    Cargo.toml
    pyproject.toml
    src/
      lib.rs
      risk.rs
      backtest.rs
      quant.rs
    Cargo.lock
libs/
  compute/
    __init__.py
    backend.py
```

Rust crate 名称使用 `polybob-core`，Python import 名称使用 `polybob_core`。Python facade 位于 `libs.compute`，支持 `python`、`rust`、`verify` 三种模式。

## PyO3 / maturin 边界

### 边界原则

- Rust API 必须是**粗粒度批处理**，一次调用处理完整数组或完整事件块。
- 禁止 Python 每个 tick、每笔交易或每个资产调用一次 Rust 函数。
- 热路径释放 GIL，使 API 服务或研究任务可并行处理其他 Python 工作。
- Python 对外接口保持稳定，由 adapter 选择 `python`、`rust` 或 `verify` backend。
- Rust 层不访问网络、不读取业务配置、不写事实库、不生成投资结论。
- Rust 错误必须转换成有类型的 Python 异常，禁止 panic 穿过 FFI。

### 推荐 API v1

```python
polybob_core.risk_metrics(
    returns: numpy.ndarray[float64],
    equity_curve: numpy.ndarray[float64],
    confidence: float = 0.95,
    periods_per_year: int = 252,
) -> RiskMetricsResult

polybob_core.backtest_metrics(
    equity_curve: numpy.ndarray[float64],
    trade_pnl: numpy.ndarray[float64],
    fees: numpy.ndarray[float64],
    periods_per_year: int = 252,
) -> BacktestMetricsResult

polybob_core.slippage_batch(
    prices: numpy.ndarray[float64],
    sizes: numpy.ndarray[float64],
    market_depth: float,
    base_slippage_bps: float,
    volatilities: numpy.ndarray[float64],
) -> numpy.ndarray[float64]

polybob_core.rolling_zscore(
    y: numpy.ndarray[float64],
    x: numpy.ndarray[float64],
    hedge_ratio: float,
    lookback: int,
) -> numpy.ndarray[float64]

polybob_core.kalman_hedge_ratio(
    y: numpy.ndarray[float64],
    x: numpy.ndarray[float64],
    q: float = 1e-5,
    r: float = 1e-3,
) -> tuple[numpy.ndarray[float64], numpy.ndarray[float64]]
```

第二阶段只有在 profiling 证明必要时，才考虑：

```python
polybob_core.rolling_indicators(
    timestamps_ns: numpy.ndarray[int64],
    close: numpy.ndarray[float64],
    windows: list[int],
) -> RollingIndicatorsResult

polybob_core.replay_events(
    timestamps_ns: numpy.ndarray[int64],
    market_ids: numpy.ndarray[uint32],
    event_types: numpy.ndarray[uint8],
    prices: numpy.ndarray[float64],
    sizes: numpy.ndarray[float64],
    config: ReplayConfig,
) -> ReplayResult
```

## 数据类型约定

### 数值与时间

- 价格、收益率、权重、风险指标：v1 统一 `float64`。
- 时间戳：UTC Unix nanoseconds，使用 `int64`；时区转换留在 Python 边界。
- 索引、资产编码：`uint32`；事件类型和方向使用稳定的 `uint8` 枚举。
- 窗口长度、年化周期：无符号整数，并在 Python/Rust 两端校验范围。
- 金额计算暂用 `float64` 以保持现有公式一致；真实账本金额继续使用数据库定义的精度，不经由该计算内核写账。

### 缺失值与非法值

- 缺失观测统一使用 IEEE `NaN`，禁止用 `0` 代替未知值。
- `+/-inf`、空数组、非连续数组、长度不一致必须有明确处理规则。
- 输入默认要求 C-contiguous；adapter 可在边界执行一次显式复制，并记录复制成本。
- 风险指标结果必须标记 `valid_observation_count`，避免结果看似正常但样本不足。

### 结果结构

结果使用 PyO3 `pyclass(frozen)` 或具名对象，不使用位置不明的长 tuple：

```text
RiskMetricsResult
  var
  cvar
  max_drawdown
  max_drawdown_peak_index
  max_drawdown_trough_index
  sharpe_ratio
  sortino_ratio
  calmar_ratio
  valid_observation_count
```

所有字段、单位、年化方式、总体/样本标准差选择必须写入契约测试。

## Backend 与 fallback

Python adapter 已支持三个显式模式：

| 模式 | 行为 | 用途 |
| --- | --- | --- |
| `python` | 只运行现有 Python 实现 | 默认基线与应急回退 |
| `rust` | 只运行 Rust；失败后按策略回退并告警 | 验证完成后的生产模式 |
| `verify` | Python 与 Rust 同时运行、比较结果、返回 Python 结果 | 灰度和语义校验 |

配置示例：

```text
POLYBOB_COMPUTE_BACKEND=python|rust|verify
POLYBOB_RUST_FALLBACK_ENABLED=true
```

fallback 要求：

- 扩展导入失败时记录结构化事件，包含平台、扩展版本和错误类别。
- Rust 计算错误只能回退到同版本 Python 公式，不能返回零值或空成功结果。
- 回退次数、耗时、差异超限必须进入指标与日志。
- `verify` 模式发现超过容差的差异时，自动熔断 Rust backend。
- 真实执行风控不得依赖尚未完成灰度验证的 Rust 结果。

## Benchmark Gate

### 基线工具

- Python：`pytest-benchmark` 或 `pyperf`，分离冷启动和稳态。
- Rust：Criterion，用于 crate 内核微基准。
- 端到端：从 Python 调用扩展，包含 FFI、数组转换和输出构造成本。
- CPU profiling：Python 使用 `py-spy`/`scalene`；Rust 使用 Instruments 或 `cargo flamegraph`。

### 数据集

每个候选至少包含：

- 小：1 千观测，用于测量 FFI 固定成本。
- 中：10 万观测，代表常规研究任务。
- 大：1 千万观测或可接受的最大真实历史样本，代表批量回测。
- 边界集：空、单元素、常数、NaN、极端值、非连续数组。
- 真实脱敏样本：来自 PolyBob 已保存的真实市场历史数据，不允许随机数据作为唯一依据。

### 正确性门禁

- Python 和 Rust 使用同一 fixture 与 golden result。
- 有限值默认绝对误差 `<= 1e-12`、相对误差 `<= 1e-9`；确需放宽必须逐指标说明。
- 索引、交易数量、方向、拒单结果等离散输出必须完全一致。
- NaN、inf、零方差、空数据语义必须完全一致。
- 属性测试覆盖单调权益无回撤、常数收益零波动、CVaR 不小于 VaR 等不变量。
- 在 shadow/verify 模式连续运行至少一周或完成足量离线真实数据重放，无未解释差异。

### 性能门禁

模块只有同时满足以下条件才值得迁移：

- profiling 显示该模块占目标工作流 CPU 时间至少 `20%`，或其 P95 延迟已超过产品预算。
- 中/大数据集端到端稳态至少比当前 Python/NumPy/Numba 实现快 `2x`。
- 小数据集不得比 Python 慢超过 `20%`；否则 adapter 必须按数据规模路由。
- 峰值内存不高于 Python 基线的 `1.25x`，且不得产生重复的大数组复制。
- 连续 10 次基准的中位数满足门禁，变异系数应低于 `5%`。
- 编译、打包和启动复杂度有明确所有者，CI 增量时间处于可接受预算。

若只达到 `1.2x` 至 `1.5x`，优先保留 NumPy/Numba，避免增加双语言维护成本。

## 迁移阶段

### Phase 0：测量，不写 Rust

- 建立 Daily Brief、股票页、回测和风险汇总的端到端延迟预算。
- 采集 CPU profile、I/O 等待、数据库查询和前端渲染证据。
- 为风险指标和回测建立真实数据 benchmark fixtures。
- 固化现有 Python 语义，包括当前边界行为和已知缺陷。

退出条件：能回答“时间花在哪里”，并确认至少一个候选满足 `20%` CPU 占比门槛。

### Phase 1：风险指标 PoC

- 实现 VaR、CVaR、最大回撤、Sharpe、Sortino、Calmar 的 Rust 纯函数。
- 用 maturin 构建本地 wheel；不接入默认运行路径。
- 建立 Python/Rust 交叉测试、属性测试和端到端 benchmark。

退出条件：正确性门禁全过，且真实中/大数据集达到 `2x`。

### Phase 2：Adapter 与 shadow 验证

- 增加 backend adapter，但默认仍为 `python`。
- `verify` 模式抽样双算，记录耗时和差异。
- 建立自动熔断、fallback 和扩展版本可观测性。

退出条件：离线重放和 shadow 验证无未解释差异，fallback 演练通过。

### Phase 3：回测纯数值核

- 迁移批量滑点、权益曲线统计、交易 PnL 聚合。
- 业务状态机、策略回调、日志和数据读取仍留在 Python。
- 只有在事件状态机本身成为热点时，才设计 columnar replay kernel。

退出条件：完整回测结果逐字段一致，端到端而非微基准达到性能门禁。

### Phase 4：可选扩展

按新的 profile 排序评估：

1. 多资产 rolling indicators。
2. Parquet/Arrow 历史数据扫描与过滤。
3. 大规模订单簿增量聚合。
4. 批量组合风险矩阵。

每项均重新走 Phase 0 至 Phase 2，不因已有 Rust crate 而自动批准迁移。

## 发布与构建

- 使用 maturin 构建 Python wheel，版本与 PolyBob 发布版本绑定。
- 优先支持项目实际使用的平台和 Python 3.11；扩展平台前先验证 CI 成本。
- macOS 构建必须覆盖当前机器架构，并验证 wheel 的签名、加载和最低系统版本。
- CI 至少执行 Rust format、clippy、unit tests、Python cross-tests 和 wheel import smoke test。
- 不要求开发者仅为运行核心 Python 路径安装 Rust toolchain；已构建 wheel 或 Python fallback 必须可用。
- Rust crate 锁定依赖并进行供应链审计；避免引入不必要的高层框架。

## 主要风险

| 风险 | 影响 | 控制措施 |
| --- | --- | --- |
| 迁移了错误的瓶颈 | 复杂度增加但用户无感 | 强制 Phase 0 profiling 和端到端门禁 |
| FFI 粒度过细 | Rust 更快但整体更慢 | 仅批量 API，测量数组转换成本 |
| Python/Rust 公式漂移 | 风险与回测结论不一致 | 单一契约、golden tests、verify 模式 |
| NaN/空值语义变化 | 将未知误报为零风险 | 明确缺失值协议和属性测试 |
| NumPy 数组复制 | 内存和延迟反而上升 | 连续数组契约、暴露复制指标 |
| maturin/wheel 平台问题 | 本地或部署无法启动 | Python fallback、wheel smoke test |
| 双语言维护负担 | 迭代速度下降 | 只迁高收益稳定内核，保持 API 极小 |
| Rust panic/越界 | 服务异常 | 输入校验、Result 错误、禁止 panic 穿 FFI |
| 过早接入执行路径 | 错误影响真实资金 | 先离线、再 shadow，最后才允许用于风控 |
| 基准失真 | 优化随机数据而非真实负载 | 使用真实脱敏数据和端到端工作流 |

## 决策清单

开始任何 Rust 实现前，负责人必须对以下问题给出可验证答案：

- 该函数在真实工作流 CPU profile 中占比是多少？
- 当前 NumPy/Numba/SciPy 实现是否已排除明显低效调用？
- 输入输出是否能表达为少量连续数组？
- 端到端加速目标和延迟预算是什么？
- Python 与 Rust 的公式、NaN、年化和边界语义是否已冻结？
- wheel 加载失败时用户会看到什么，系统如何回退？
- 谁负责 Rust crate、构建链、CI 和安全更新？
- 若实测不足 `2x`，是否愿意删除 PoC 并保留 Python？

只有这些问题都有明确答案，`polybob-core` 才应从架构方案进入生产实现。
