# PolyBob 架构

## 一句话

**一台研究仪器,带一条很薄的执行尾巴。** 不是一个交易系统。

之前代码的形状是后者:17 个"service"、执行引擎、风险管理、模拟盘、RL 优化器 ——
而可开仓的边是 0 条。约 80% 的代码服务于一个没有东西可执行的执行栈,而决定成败的
研究闭环是 `scripts/` 里几个脚本加手工形状的 JSON。比例是倒挂的,这份文档记录
把它掰正的结果。

## 四层

```
libs/data/       时间轴数据层   ← 地基,一切可复现性的来源
libs/quant/      研究与判定     ← 假设 → 实验 → 证据 → 门禁
libs/portfolio/  组合与仓位     ← "收益 = 优势 × 仓位" 的第二半
apps/            API + 前端     ← 薄
modules/         内部模块       ← 一个进程里的包,不是微服务(见 modules/README.md)
```

### 1. 数据层:两个时间轴

`libs/data/store.py`。每一行都带两个日期:

- `event_date` —— 事情在市场上发生的时间
- `fetched_at` —— **我们**知道它的时间

第二个是全部要点。有了它,"我在 3 月 1 日知道什么"是一个过滤条件而不是一种想象。
`store.read(..., as_of=X)` 只返回在 X 之前观测到的行,过滤发生在 store **内部** ——
所以 look-ahead 是**写不出来**的,不是"测试会抓到"。

这一层解决的是一个实测到的缺陷:同一份缓存、同一段代码,内部人实验一天返回
n=753,第二天返回 n=667。旧的 `data/market_cache/` 是 613 个会被覆盖、不带时间戳的
JSON,所谓"缓存"就是提供商最后一次返回的东西。

写入是 **append-only**。重新抓一天已存在的数据会追加一条 `fetched_at` 更晚的观测;
读取取 as_of 之前最新的那条。于是提供商悄悄修改历史变成**可见的**(两行、两个日期),
而不是把旧值销毁。`store.restatements()` 直接查"我的样本里有多少被事后修订过"。

存储用 Parquet + DuckDB:无服务、无 schema 迁移,306MB 原始 JSON 变成 10MB。

**`libs/data/run_manifest.py`** 钉住一次运行的三件事:观测切点 `as_of`、代码状态
(commit + 是否 dirty)、参数。写在证据文件旁边。看板**要求** trade 行有 manifest ——
没人能复现的结果是一个说法,不是证据。

**`libs/data/universe.py`** —— 标的范围声明一次。同一批列表以前在 5 个脚本里各写一遍
且已经漂移(10 只 / 5 只 / 20 只)。范围是假设的一部分:"内部人集群预示收益"在
20 只巨头上和在全部 SEC 申报人上是不同的断言。

### 2. 研究层:一条边只有一处定义

`libs/quant/edge.py` 的 `Edge` 协议声明决定一个结果的全部要素 —— 范围、入场、
**出场**、成本、持有期、方向。`libs/quant/edge_backtest.py` 回放它产出证据;
实时扫描问它今天什么在触发,并报告**它自己声明的**出场规则。

这修的是一个具体的裂缝:内部人边曾存在三份实现,而只有实验脚本有出场规则。
后果很精确 —— 看板批准的是"持有 20 个交易日、相对 SPY 超额、扣 10bps 成本的策略",
产品呈现的是"一个没有出场的信号"。这是两个不同的东西,只有前者有证据。

统计层:`libs/quant/clustered_inference.py`(聚类标准误 + 整簇 bootstrap + 符号检验)、
`libs/quant/hypothesis.py`(试验计数,含跑过就放弃的探索性扫描)、
`libs/quant/event_study_board.py`(门禁,自己重算 t 值而不是抄)。

### 3. 组合层:仓位的地基

`libs/portfolio/`。账户权益是**录入的**,不是猜的 —— 以前是写死的 100,000,让"买多少"
这个字段变成编造的数字。Kelly 接上真实账户,再按独立单元数打折(样本短就下注小),
再受单笔/单域/全账户风险三重预算约束。跨域相关性默认 0.5 而不是 0:
美股多头和山寨币空头在风险资产抛售时**同向亏损**,按独立相加会让两个同向的赌注
看起来像对冲。

### 4. 前端

17 页 → 13 页。`execution` / `simulation` / `risk-ops` / `strategies` 进了 `attic/`:
四个操作界面服务 0 条策略。**页面的形状是一种承诺**,把数字清空并不能收回它。

## 借了什么,没借什么

- **Point-in-Time 进存储层** —— 学 [Qlib](https://qlib.readthedocs.io/en/latest/component/data.html)。
- **Common core** —— 学 [NautilusTrader](https://nautilustrader.io/docs/latest/concepts/architecture/):
  回测和实盘共用一个内核,只有 adapter 不同。这里的工作单元不是订单路由器而是"边",
  所以 common core 就是 `Edge` 协议。
- **没有**整体迁移到 Qlib 或 Nautilus。Qlib 是因子/ML 中心的,表达不了这种基于替代
  数据的事件研究;Nautilus 的价值在真实成交模拟和交易所 adapter —— 在没有东西可交易
  的时候是零价值。而这个项目有它们都没有的东西:聚类推断 + 试验计数 + fail-closed 门禁。
- **没有**引入 MLflow / DVC / feature store。单人项目上这些是负担;等价物是
  `run_manifest.py` 那 150 行。

## 不变量(CI 强制)

1. `data/promotion_board.json` 必须能从证据逐字节重建(`event_study_board.py --check`)。
2. 看板上任何 approved 行的 t 值必须是聚类标准误算的,独立单元 ≥ 20。
3. trade 行必须有可复现的 run manifest。
4. `data/market_cache/` 和 `data/store/` 不得进 git;`promotion_board.json` 和
   `hypothesis_registry.json` 必须在。
5. 缺失就是缺失 —— 任何"取不到数据"都不能变成一个数字。

## 现状

**可开仓的边:0 条。回避过滤器:1 条**(A股龙虎榜,125 个独立周,t=-6.85)。

两条曾经通过的边在聚类标准误下掉到门槛以下(t 从 5.03→2.35 和 6.43→1.81,
门槛 4.19),且独立单元只有 9 和 13(需要 ≥20)。唯一的复活路径是**把样本期拉长到
覆盖更多独立行情段** —— 在同一批周里堆更多事件不会改变任何结论。
