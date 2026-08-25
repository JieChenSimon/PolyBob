# BTC 1m clean_v2 源数据退役记录（2026-08-25）

## 退役对象

仅退役已经完成去重压缩、消费者切换和回放验证的精确目录：

```text
data/datasets/parts/btc_1m_bars_clean_v2
```

源目录包含 2 个 Parquet、80,206 行、2,047,164 bytes。保留并继续使用的替代物为：

```text
data/datasets/compacted/btc_1m_bars_clean_v2/dataset/symbol=BTC-USDT/data_0.parquet
```

该输出包含 50,000 行去重后的 `event_at` 数据，使用 Zstandard Parquet；逐源哈希、字节数、行数、schema 哈希和输出哈希已写入
`compaction_manifest.json`。

## 删除前门禁

- 方向回放、动量回放和资源审计均已切换为压缩路径；旧路径不再作为运行时 fallback。
- 历史重建脚本改写入隔离的 `btc_1m_bars_rebuild`，不会重新创建已退役的回放输入目录。
- dry-run 验证了 2 个精确源文件、源哈希、源行数、输出文件和输出哈希。
- 使用真实压缩数据运行 20 行 `SimulationService` smoke test：状态 `PASS`，CPU fraction 0.3218，交易数和显式成本基线一致，SQLite/WAL/SHM 关闭后均清理。

## 退役结果与删除后验证

- 已删除 2 个源 Parquet，释放 2,047,164 bytes；没有执行宽泛目录删除。
- `verify-retired` 验证：源文件缺失数 2/2，输出文件校验 1/1。
- 删除后真实回放仍可读取压缩输出并生成相同账本结果。
- manifest 保留 `RETIRED` tombstone、源清单和输出证据，支持审计而不是留下可误读的活跃路径。

## 研究边界

该退役只改变存储和回放输入路径，不增加任何策略 alpha。smoke test 仍显示报价深度为 `missing_depth`，且样本不足 12 个完整月，因此不能把该结果当作收益目标或实盘 Promotion 证据。
