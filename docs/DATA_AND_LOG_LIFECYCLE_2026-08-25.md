# 数据集与日志生命周期审计

## 当前盘点

本次只读盘点针对工作区当前真实文件，未删除或覆盖任何数据：

| 区域 | 文件数 | 逻辑大小 | 观察 |
|---|---:|---:|---|
| `data/` 总体 | 143,581 | 约 4.4GB | 小文件治理必要 |
| `data/store/insider_filings` | 79,464 | 约 312MB | 平均约 3KB，约 79,074 个小于 4KiB，优先合并 |
| `data/store/daily_bars` | 18,009 | 约 273MB | 平均约 14KB，按标的/时间批量合并 |
| `data/market_cache/btc5m` | 21,680 | 约 213MB | 约 14,447 个小于 4KiB，按请求/时间窗口做 TTL 和批量归档 |
| `data/datasets/raw` | 14,710 | 约 761MB | SEC/legacy 原始响应；不可直接删除，保留内容寻址和 manifest |
| `data/datasets/parts/sec_filings` | 1,146 | 约 1.3GB | 已是较合理的规范化 Parquet 分区 |
| `data/.kernel_replay_btc5m_direction` | 36 | 约 170MB | SQLite/WAL/SHM 临时回放物，需 run 状态和 finally 清理 |

另有 4 个 `output/` 截图、少量报告和 Playwright 控制台日志。应用主日志当前默认输出到 stderr，盘口原始事件日志已经使用有界 SQLite、批量 flush、保留天数和最大行数；需要继续统一运行日志格式和轮转策略。

## 来源分类与处理决策

### 必须保留的原始证据

SEC、交易所和其他 provider 的原始响应必须保持不可变、内容寻址、可通过 manifest 找回。它们可能是许多响应文件，但这是 provenance 和重放要求，不应为了“文件数好看”拼接后丢失请求边界或哈希。重复内容由哈希去重，重复 manifest 事实不应继续增长。

### 应当合并的规范化数据

`store/insider_filings` 和 `store/daily_bars` 是当前最明显的小文件来源。目标布局不是单一超大文件，而是按数据集、资产域/标的、时间分区的 ZSTD Parquet，目标文件以批量行数和合理字节范围控制。合并结果必须是新目录，经过行数、schema、哈希、PIT 查询和重放对比后，才能切换查询层。

### 必须有 TTL 的缓存

BTC 响应缓存、SEC 请求缓存、模型下载缓存和浏览器测试产物应按 provider/request/时间窗口分层，设置 TTL、容量上限和清理计数。缓存不能作为唯一研究事实源；清理缓存不能删除已物化的 canonical dataset。

### 必须短生命周期的临时物

回放 SQLite、`-wal`、`-shm`、checkpoint 和中间结果需要绑定 `run_id`，写入状态和进度，成功、取消、异常都执行 finally 清理；需要长期审计的账本应显式归档到 archive，而不是留在 `.kernel_replay_*` 临时目录。

## 已落地的安全工具

`scripts/dataset_file_governance.py` 提供：

- `inventory`：只读统计文件数、字节数、扩展名和小文件数量；
- `compact --source ... --destination ...`：默认只输出 dry-run 方案；
- `compact ... --apply`：使用 DuckDB 流式读取并写入新的分区 ZSTD Parquet，生成 `compaction_manifest.json`；
- 默认拒绝写入非空目标目录，不删除源目录；可选 exact-row 去重，但不默认删除 PIT 不同的历史观测。

本轮尚未对生产数据执行 `--apply`，因为必须先补齐行数、schema、PIT、哈希和回放等价性验收；这避免把“清理文件”变成不可恢复的数据损失。

## 下一步验收

1. 对 insider/daily bars 生成 compacted copy，比较行数、列 schema、PIT 查询、重复率和关键策略回放结果。
2. 仅在验证通过后切换 canonical query path，并保留旧 raw/archive 作为可恢复证据。
3. 为 response cache 和 Playwright 产物增加 TTL/容量上限与清理审计。
4. 把回放临时目录清理接入成功/取消/异常 finally，验证进程关闭后无无主 WAL/SHM。
5. 将应用日志统一为结构化事件、级别、run_id/request_id、错误分类，按大小/日期轮转、压缩和保留。
