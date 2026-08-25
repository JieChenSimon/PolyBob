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

结果：扫描美股 200 个、A 股 200 个，共 400 个名录成员；其中 33 个同时具有至少 200 根本地真实日线、价格基准明确且达到成交额门槛（美股 31、A 股 2），367 个为 `UNKNOWN`。这不是收益结论，也不是交易批准；它是下一阶段逐标的研究的候选入口。

本次清单中 A 股已有本地覆盖的候选使用 `forward_adjusted`；美股若没有本地历史不会被补成可研究。供应端异常写入 `provider_errors`，不会回退到手工常量。

## 全市场扫描验证

显式省略 `--limit` 后完成了真实全量扫描，结果写入
`data/discovered_equity_universe_full.json`：

- SEC + A 股名录共 15,410 个成员；美股 9,860 个，A 股 5,550 个。
- 通过本地历史、明确价格基准、最近 60 日中位成交额和 14 天 freshness 门禁：
  39 个（美股 31、A 股 8）。
- 其余 15,371 个保持 `UNKNOWN`。本轮还将含 `unknown` 的价格基准标签拒绝，
  并把 Yahoo 的复权 OHLCV 明确标记为 `yahoo_split_dividend_adjusted_ohlcv`。
- 全量发现耗时约 14 秒，没有对 12,751 个缺少本地分区的名录成员执行逐个
  Parquet 读取。

完整 manifest 与研究用限额 manifest 分离：完整清单用于自主发现和分批预热；
`data/discovered_equity_universe.json` 作为当前 33 个标的的可控研究输入，
避免未经筛选地启动数万 case 回放。

## 复权数据与全量 Paper Lab 验证

为避免拆股/分红跳变污染长期研究，Yahoo 日线缓存要求完整的 `adjclose` 序列，
并以 `adjclose/raw_close` 同比例调整 OHLC、反向调整成交量。该序列适合总收益
研究，但不等同于真实可成交的原始报价，模拟盘仍必须把报价深度和执行质量标为
UNKNOWN/DEGRADED。

全量 manifest 刷新后，24 个美股标的通过稳定性/质量筛选并进入 Paper Lab：

- 纸面执行回放：总收益 `+90.91%`，最大回撤 `14.95%`，Sharpe `0.87`，
  1,424 笔交易，显式费用与滑点合计 `6,803.78`。
- 年化/每月收益目标门禁：`FAIL`，年化约 `14.62%`。
- 所有成交均缺少盘口深度证据，不能把该回放升级为真实执行可行性结论。
- 训练期选择的组合在严格样本外相对等权基准为 `-10.57%`，所以状态仍为
  `replay_only_not_promoted`。

这组结果说明“自主发现和真实数据回放链路已跑通”，但没有证明策略具备稳定
超额收益；下一轮必须先解决同期样本外落后和报价深度缺失，再讨论参数优化。

## 受控自动预热验证

新增 `scripts/warm_equity_universe.py`，从完整 manifest 的 UNKNOWN 队列中按域
分批预热。它具备每批最大标的数、请求间隔、重试次数、总时间预算和原子 JSON
checkpoint；成功结果由真实 provider fetcher 镜像到 PIT daily-bar store，失败
保留 `UNKNOWN_FETCH_FAILED` 与异常，不会升级为 READY。

本轮真实执行参数为美股最多 5 个、请求间隔 1 秒、2 次尝试、120 秒预算：

- 4 个成功（A、AA、AAAU、AACB），分别获得 324--1,254 根真实日线，最新日期
  为 2026-08-21 或 2026-08-24，价格基准均为
  `yahoo_split_dividend_adjusted_ohlcv`。
- AAC 因 Yahoo 返回 HTTP 404，在两次尝试后保持 UNKNOWN；错误被 checkpoint
  记录，没有被吞掉。
- 重新发现后，全量 READY 从 39 增至 42；限额研究清单 READY 从 33 增至 36。

这验证了“自主发现 → 受控真实数据预热 → 重新质量筛选”的闭环，但仍未表示
15,410 个名录成员都已下载；后续应按每日预算持续运行，并在每批数据完成后再
进入逐标的样本外研究。

## 约束与下一步

发现器当前按 SEC/A 股名录和本地已落盘数据筛选，尚未把所有名录成员自动下载成历史数据；这是有意的资源安全边界，避免一次扫描造成大量网络请求、磁盘写入和不可控供应端压力。下一轮应以限速、断点、重试和每日预算把 `UNKNOWN` 分批预热，再逐标的进入完整样本外模拟盘与 Promotion 门禁。
