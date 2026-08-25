# PB-0039 真实 BTC 5 分钟数据扩展记录

更新时间：2026-08-25（Asia/Singapore）

## 已完成

- 通过 OKX `market/history-candles` 拉取真实 BTC-USDT 1 分钟 K 线。
- 本轮请求 30,000 根 1 分钟 K 线，原始响应写入本地 data lake，记录 source、request、observed_at 和 SHA-256。
- 生成 `data/btc5m_calibration.json`：30,000 根原始 1 分钟 K 线、5,994 个可用 5 分钟窗口、22 个独立自然日。
- 真实波动率概率模型相对旧猜测波动率模型的 Brier score：
  - 决策后 1 分钟：0.2355 → 0.2195
  - 决策后 2 分钟：0.2197 → 0.1851
  - 决策后 3 分钟：0.2027 → 0.1471

## 仍未通过的门禁

- 这份结果的状态仍是 `calibration_only_not_trading_evidence`，不能据此宣称盈利或放行交易。
- 当前已提交的 BTC 5m settled-window 报告仍只有 3,545 个窗口；本轮 1m 校准数据尚未自动重建为与交易报告同一版本的 settled-window 数据集。
- 因此成本后成交、时间切分、逐日/逐月收益、回撤和 Promotion Board 验收尚未通过。
- 本轮数据中发现 normalized 1m dataset 可能存在跨 part 的重复时间戳，下一步必须先完成可重放去重/版本化，再进入交易收益审计。

结论：数据覆盖门槛已达到，但交易有效性结论仍为 `UNKNOWN`，不允许把校准改善当作收益改善。

## 2026-08-25 settled-window 增量

随后使用可恢复 checkpoint 继续采集真实 OKX settled-window，当前本地 v6 数据为
3,932 个唯一窗口、15 个独立自然日；采集失败数为 0。通过
`scripts/compact_btc5m_v6.py --apply` 已将 5 个小分区压缩为 1 个规范 Parquet
part，并保留旧 parts 的归档，避免研究阶段持续堆积小文件。该数据仍少于 PB-0039
要求的 20 个独立日，因此逐日/逐月收益与样本外目标门禁仍不能标记完成。

当前状态：`UNKNOWN` / `research_only`。方向代理策略此前在成本压力下为负，不能
用未具备真实盘口深度的事件报价压力测试替代真实可成交证据；后续回放会继续记录
资源使用和完整结果，未完成运行不作为正式收益结论。

本轮事件内核回放在约 6 分钟处因 CPU 瞬时达到约 72% 被安全中止；最终 JSON 仍保留
上一份完整结果，临时 SQLite 文件已由内核清理。由此确认当前“单次长事务 + 每事件
账本写入”仍不满足资源护栏，不能标记 PB-0043 完成；下一步应实现分段 checkpoint
与可恢复批次后再重放。

后续验证又发现：即使采用分段 checkpoint、动态限速和固定 100ms 节拍，SQLite
密集阶段仍可能出现 69--75% 的瞬时 CPU 峰值，因此这些运行均被安全中止，未覆盖
正式结果。已进一步将 `SimulationStore` 的 schema/migration 初始化改为实例级一次性
执行，避免每次账本操作重复扫描 schema；相关服务、API 和回放测试共 59 项通过。
下一轮应从现有 checkpoint 恢复，并用外部资源 watchdog 对总 CPU 做硬门禁后再生成
正式成本情景结果。

另确认 SQLite 回放连接默认使用 `synchronous=FULL` 与较小 WAL 自动 checkpoint，
这会把单笔审计提交的 CPU 峰值放大。回放专用路径现支持显式记录的
`synchronous=NORMAL` 与较大 WAL checkpoint 间隔；生产/实时模拟盘默认配置不变，
该降级仅用于可恢复的研究临时库，结果仍通过 WAL、分段 checkpoint 和完整账本校验。

进一步发现回放在每个事件调用整本 `list_positions`，随成交数增长形成 O(n²) 扫描；
新增按标的索引查询 `get_position` 并改用该路径，相关服务/API/回放测试继续通过。

回放还关闭了已存在 checkpoint 数据库的重复 `journal_mode=WAL` 协商，并将逐笔
INFO 日志降为 WARNING；这些只影响研究回放的运行开销，不改变成交、结算或账本
数据。正式生产模拟盘仍使用默认日志和 SQLite 配置。
