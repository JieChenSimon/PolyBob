# PB-0044 数据与临时物盘点（2026-08-25）

## 当前基线

| 区域 | 文件数 | 磁盘占用（du -sk） | 主要内容 |
|---|---:|---:|---|
| `data/store` | 100,679 | 649,140 KiB | bitemporal daily bars、fundamentals、insider filings |
| `data/market_cache` | 26,983 | 1,200,184 KiB | provider/cache 响应与 `.bin`/JSON |
| `data/datasets` | 24,255 | 2,450,232 KiB | 规范化 Parquet、parts、归档 |
| `data/.kernel_replay_insider` | 未单独计数 | 18,820 KiB | 回放临时/检查点物 |

主要扩展名为 Parquet 107,498 个、BIN 17,432 个、JSON 15,052 个、BODY 11,911
个。`data/store`、`data/market_cache`、`data/datasets` 中小于 64 KiB 的文件数
分别为 100,679、26,624、22,639；这说明小文件问题是真实的，且主要集中在
按 payload/响应拆分的不可变数据和缓存层。

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

本报告是只读盘点，不代表 PB-0044 的三个验收项已经完成。
