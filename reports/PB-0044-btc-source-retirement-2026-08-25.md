# PB-0044 BTC 1m 源 parts 退役记录（2026-08-25）

## 退役对象

仅退役以下已压缩且已验证的旧源目录：

```text
data/datasets/parts/btc_1m_bars
```

退役前共 5,143 个 Parquet 文件、346,042 行、16,126,138 bytes。保留并继续使用的压缩数据为：

```text
data/datasets/compacted/btc_1m_bars/symbol=BTC-USDT/part-compact-00000.parquet
```

该文件为单个 Zstandard Parquet，2,252,519 bytes。

## 删除前验收

- 压缩状态为 `APPLIED`，验证状态为 `verified=true`。
- 压缩前后行数均为 346,042，代表性源文件与压缩文件字段结构一致：
  `symbol, event_at, open, close, source, observed_at`。
- 压缩清单记录全部 5,143 条输入路径、输出 SHA-256、源 manifest SHA-256 和行数。
- 删除前 5,143/5,143 条输入路径均存在；源目录和输出目录均没有 pending、tmp、partial、WAL 或 SHM 文件。
- 运行代码、测试、配置中没有引用该精确旧目录；仍保留的 `btc_1m_bars_clean_v2` 等数据集不是本次退役对象。

## 退役结果

删除动作只针对上述精确目录，不涉及 `data/datasets/parts` 下其他数据集、压缩输出、manifest、回放数据或缓存。删除后必须再次验证压缩文件可读、行数不变、完整测试和任务板校验通过。

退役后的运行观察发现，BTC 5 分钟采集器曾将一次新的 2 行 1m 响应写回旧数据集名，短暂重新创建 1 个旧目录 part。已将采集器的实时暂存目标改为 `btc_1m_bars_live`，并加入回归测试；该临时旧 part 及其 manifest 登记已再次清除。历史压缩数据仍是只读基线，实时增量不再污染已退役目录。

原始 5,143 个小文件本身不再可从本机恢复；其数据内容由压缩 Parquet 保存，输入路径和校验信息由 `data/btc_1m_bars_compaction_manifest.json` 与 `data/btc_1m_bars_compaction_plan.json` 保留。
