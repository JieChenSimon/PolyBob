# PB-0044 数据与临时物盘点（2026-08-25）

## 当前基线

| 区域 | 文件数 | 磁盘占用（du -sk） | 主要内容 |
|---|---:|---:|---|
| `data/store` | 100,679 | 649,140 KiB | bitemporal daily bars、fundamentals、insider filings |
| `data/market_cache` | 26,983 | 1,200,184 KiB | provider/cache 响应与 `.bin`/JSON |
| `data/datasets` | 24,255 | 2,450,232 KiB | 规范化 Parquet、parts、归档 |
| `data/.kernel_replay_insider` | 未单独计数 | 18,820 KiB | 回放临时/检查点物 |

可重复审计工具 `scripts/audit_data_layout.py` 的当前结果为 151,921 个文件、
约 4.18 GB；主要扩展名为 Parquet 107,498 个、BIN 17,432 个、JSON 15,052 个、
BODY 11,911 个。`data/store`、`data/market_cache`、`data/datasets` 中小于 64 KiB
的文件数分别为 100,679、26,624、22,639；这说明小文件问题是真实的，且主要集中在
按 payload/响应拆分的不可变数据和缓存层。

现有 `data/datasets/manifest.jsonl` 有 23,741 条路径记录，当前路径存在率为
100%。按“类别 + 文件大小 + 扩展名”的低成本元数据分组得到 7,776 个候选组、
140,718 个候选文件；这只是筛选线索，不是重复内容证明，当前确认的 hash 重复数
仍为 0（尚未执行全盘 hash）。

## 解释与风险

- `data/store` 的 `payload-<sha256>.parquet` 具有内容寻址特征，不能按文件名直接
  删除或合并；必须保留 manifest、PIT、来源和 hash 到规范分区的映射。
- `market_cache` 同时承载可重试缓存和原始响应，缓存与证据的保留级别尚未完全
  分离；直接清理可能破坏可重放和限速恢复。
- `datasets/parts` 已有规范化数据和 archive 两类物；合并前必须按 schema、symbol、
  时间范围和 provenance 去重，不能只按文件大小或路径判断重复。
- 当前没有执行删除、覆盖或全盘 hash 扫描；全盘逐字节扫描会额外产生高磁盘读负载，
  需要后续按大小分组、抽样验证、再分批低优先级 hash。

## 后续可执行步骤

1. 建立 `raw_evidence / normalized / cache / replay_tmp / logs` 五级布局和保留策略。
2. 从现有 manifest 生成文件级 lineage 索引，先按 `(size, schema, symbol, time-range)`
   聚类，再对候选重复组做限速 hash。
3. 将 insider/fundamental payload 合并为带分区索引的规范 Parquet，并保留只读归档
   与可恢复迁移清单。
4. 对回放 SQLite、WAL、进度文件和日志建立轮转、TTL、关闭清理与恢复测试；任何
   UNKNOWN lineage 都不删除。

## 首个旁路压缩验证

已对 `data/datasets/parts/btc_1m_bars` 执行旁路压缩：5,143 个输入 Parquet、
346,042 行、16,126,138 bytes 被压缩为 1 个 Zstandard Parquet、2,252,519 bytes。
删除前已验证输出可读、行数与字段结构一致、5,143/5,143 个输入路径存在且有血缘记录，
运行代码没有引用该精确旧目录；随后已退役并删除这处旧源 parts。压缩输出、两个压缩
清单和其他数据集仍保留。详细删除验收见 `PB-0044-btc-source-retirement-2026-08-25.md`。

可重复入口：

```text
uv run --locked python scripts/audit_data_layout.py --output data/data_layout_audit.json
```

本报告是只读盘点，不代表 PB-0044 的三个验收项已经完成。
