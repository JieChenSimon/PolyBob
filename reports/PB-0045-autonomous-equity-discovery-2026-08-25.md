# PB-0045：自主发现美股与 A 股候选标的

## 已实现

- `libs/data/universe_discovery.py`：统一发现接口。
- 美股名录：SEC 官方 `company_tickers.json`，保留 SEC ticker 来源。
- A 股名录：AkShare `stock_info_a_code_name()` 真实代码/名称名录。
- 可研究性门禁：本地 `daily_bars` 行数、日期覆盖和 `price_basis`；不足或价格基准未知均为 `UNKNOWN`。
- 可执行性门禁：最近 60 根日线中位成交额默认不少于 500 万；缺失成交量或低于门槛仍为 `UNKNOWN`。
- `scripts/discover_equity_universe.py`：按域限额、顺序扫描，避免一次意外读取整个 SEC 名录；输出 JSON manifest。
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

## 约束与下一步

发现器当前按 SEC/A 股名录和本地已落盘数据筛选，尚未把所有名录成员自动下载成历史数据；这是有意的资源安全边界，避免一次扫描造成大量网络请求、磁盘写入和不可控供应端压力。下一轮应以限速、断点、重试和每日预算把 `UNKNOWN` 分批预热，再逐标的进入完整样本外模拟盘与 Promotion 门禁。
