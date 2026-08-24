# PB-0045：自主发现美股与 A 股候选标的

## 已实现

- `libs/data/universe_discovery.py`：统一发现接口；全量扫描先读取本地
  `daily_bars` 分区索引，缺少本地数据的名录成员直接记录 UNKNOWN，不逐个
  打开不存在的 Parquet 文件。
- 美股名录：SEC 官方 `company_tickers.json`，保留 SEC ticker 来源。
- A 股名录：AkShare `stock_info_a_code_name()` 真实代码/名称名录。
- 可研究性门禁：本地 `daily_bars` 行数、日期覆盖和 `price_basis`；不足或价格基准未知均为 `UNKNOWN`。
- 新鲜度门禁：最新本地日线超过 14 天未更新则为 `UNKNOWN`，避免把长期停更
  的数据误当成当前可研究标的。
- 可执行性门禁：最近 60 根日线中位成交额默认不少于 500 万；缺失成交量或低于门槛仍为 `UNKNOWN`。
- `scripts/discover_equity_universe.py`：支持按域限额扫描，也支持显式全量扫描并输出 JSON manifest。
- `simulation_research_pipeline.py --discovered-manifest ...`：只接收 manifest 中 `READY_FOR_RESEARCH` 的标的进入研究管线，未知标的不会被偷偷加入。

## 真实缓存验证

命令：

```text
uv run --locked python scripts/discover_equity_universe.py \
  --domain us_equity --domain a_share --limit 200 \
  --output data/discovered_equity_universe.json
```

结果：扫描美股 200 个、A 股 200 个，共 400 个名录成员；其中 41 个同时具有至少 200 根本地真实日线、价格基准明确且达到成交额门槛（美股 33、A 股 8），359 个为 `UNKNOWN`。这不是收益结论，也不是交易批准；它是下一阶段逐标的研究的候选入口。

本次清单中 A 股已有本地覆盖的候选使用 `forward_adjusted`；美股若没有本地历史不会被补成可研究。供应端异常写入 `provider_errors`，不会回退到手工常量。

## 全市场扫描验证

显式省略 `--limit` 后完成了真实全量扫描，结果写入
`data/discovered_equity_universe_full.json`：

- SEC + A 股名录共 15,410 个成员；美股 9,860 个，A 股 5,550 个。
- 通过本地历史、价格基准、最近 60 日中位成交额和 14 天 freshness 门禁：
  1,372 个（美股 1,364、A 股 8）。
- 其余 14,038 个保持 `UNKNOWN`；除 `no_local_daily_bars` 外，明确记录了
  130 个 `latest_bar_stale>14d`，不会把停更数据混入研究。
- 全量发现耗时约 14 秒，没有对 12,751 个缺少本地分区的名录成员执行逐个
  Parquet 读取。

完整 manifest 与研究用限额 manifest 分离：完整清单用于自主发现和分批预热；
`data/discovered_equity_universe.json` 仍作为当前 35 个标的的可控研究输入，
避免未经筛选地启动数万 case 回放。

## 约束与下一步

发现器当前按 SEC/A 股名录和本地已落盘数据筛选，尚未把所有名录成员自动下载成历史数据；这是有意的资源安全边界，避免一次扫描造成大量网络请求、磁盘写入和不可控供应端压力。下一轮应以限速、断点、重试和每日预算把 `UNKNOWN` 分批预热，再逐标的进入完整样本外模拟盘与 Promotion 门禁。
