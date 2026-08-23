# data/ — 谁写谁读

这里曾经有六个结果文件、四种 schema、没有单一事实源，而**唯一决定能不能开仓的
`promotion_board.json` 是手写的** —— 它声称的 44,750 个事件在仓库里找不到对应文件，
而两个会写这个路径的脚本跑一次就会把它抹掉。下面的分层是为了让那种事不可能再发生。

## 一条单向的链

```
预注册假设            实验脚本                 原始结果文件              红绿榜                门禁            执行台
hypothesis_registry → scripts/*_experiment.py → *_results.json  →  promotion_board.json → PromotionRegistry → 策略
   (试验计数)                                    (每个数字的出处)      (唯一写入者)         (role=trade 才放行)
```

**每一层只能读上一层，不能跳级，也不能反写。**

## 文件清单

### 第一层：试验登记（多重检验的分母）

| 文件 | 写入者 | 作用 |
|---|---|---|
| `hypothesis_registry.json` | 各 `scripts/*_experiment.py` | 每个假设的预注册 + 结果。`n_trials` 按**参数配置数**计（`n_configs`），不是按假设数 |

改这个文件会改变 t 门槛，进而改变所有边的结论。它是分母，不是记事本。

### 第二层：原始结果（证据本身）

| 文件 | 写入者 |
|---|---|
| `billboard_results.json` | `scripts/billboard_experiment.py` |
| `insider_results.json` | `scripts/insider_experiment.py` |
| `us_crypto_results.json` | `scripts/us_crypto_experiment.py` |
| `btc5m_mispricing.json` | `scripts/btc5m_mispricing.py` |
| `scientific_results.json` | `scripts/scientific_experiment.py` |
| `price_edge_scoreboard.json` | `scripts/real_scoreboard.py` |
| `promotion_backtest.json` | `scripts/promotion_backtest.py` |
| `focused_board.json` | `scripts/focused_scoreboard.py` |

后三个曾经都往 `promotion_board.json` 里写，互相覆盖；现在各写各的，只能**通过第三层**
影响执行台。

### 第三层：红绿榜（唯一的权威）

| 文件 | 写入者 |
|---|---|
| `promotion_board.json` | **只有** `scripts/event_study_board.py` |

它是上一层的**纯函数**：每一行的数字都能在 `source` 指向的文件里找到，t 门槛按当前
`n_trials` 重算（绝不沿用原始文件里那个更宽松的值）。哪些边上榜由
`libs/quant/event_study_board.py` 的 `EDGE_SPECS` 预先声明——包括**方向**和**role**，
都在看到结果之前定死。

两个关键字段：

- `role: trade` — 可以开仓。必须有对应的 `strategies/<id>/config.yaml` 实现，
  否则 `tests/test_event_study_board.py` 会红。
- `role: avoid` — 回避过滤器。是真发现，但不产生收益（也做不了空），**不授予开仓权限**。
  缺少 `role` 字段 = fail-closed 不授权。

**永远不要手改这个文件。** 重跑任何实验后执行：

```bash
uv run --locked python scripts/event_study_board.py
```

`tests/test_event_study_board.py::test_committed_board_matches_the_evidence`
会验证提交的 board 能从证据完整重建。

## 缓存目录（不是结果）

- `market_cache/` — provider 响应缓存，6 小时 TTL。可以随时删。
- `market_cache/sec/` — SEC 季度批量 zip。
- `market_cache/sec_daily/` — EDGAR **每日**申报里解析出的集群买入事件，按天一个文件。
  过去的一天不会变，所以只抓一次。由 `scripts/warm_insider_cache.py` 预热；
  verdict 路径**只读缓存不抓取**（冷启动要几千个请求，不能发生在页面加载里）。

## 本地真实数据集

后续 provider 响应会同时归档到 `data/datasets/raw/`，按 SHA-256 内容寻址并写入
`data/datasets/manifest.jsonl`；相同响应只保存一份，重新抓到的不同内容会形成新的
观测记录。标准化的 BTC 1m/5m、盘口和其他任意时间粒度数据写入
`data/datasets/parts/` 的 Parquet 分区，日线、资金费、多空比、SEC 和公司行动继续
由 bitemporal store 管理。运行：

```bash
uv run --locked python scripts/migrate_cache_to_store.py
uv run --locked python scripts/catalog_datasets.py
```

目录中的原始响应不是策略结果；每个结果仍必须引用 dataset、source、event_at、
observed_at、哈希和 PIT 合同，才能进入研究晋级门禁。
