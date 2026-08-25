# PB-0044 压缩后源数据退役判定

## 结论

本次已把“压缩后在不影响使用和运行时删除源数据”的规则写入项目约束。
当前不能把 `data/` 下所有旧文件一律删除：数据角色、PIT/来源血缘和可重放边界不同。
按照新门禁，只有具有完整替代物和证据的精确 dataset 才能退役。

## 当前盘点

盘点命令：

```text
uv run --locked python scripts/dataset_file_governance.py inventory --root data
```

本次结果：146,973 个文件，5,287,412,272 bytes，144,886 个小于 64 KiB 的文件。
这些数字只说明空间和小文件规模，不证明任何文件可以删除。

## 已验证的退役对象

`data/datasets/parts/btc_1m_bars` 曾有 5,143 个 Parquet、346,042 行、16,126,138 bytes。
对应压缩输出是：

```text
data/datasets/compacted/btc_1m_bars/symbol=BTC-USDT/part-compact-00000.parquet
```

已有 compaction manifest、源文件清单、行数、来源 manifest 引用和输出哈希；输出可读，
源树已精确退役，活动 manifest 的路径覆盖检查通过，且 live collector 已切换到
`btc_1m_bars_live` 并有回归测试防止旧路径复活。相关回归测试本次通过：6 passed。

这项退役不是“删除所有 BTC 数据”：`btc_1m_bars_clean_v2` 后续已完成独立退役流程，详见
`PB-0044-btc-clean-v2-retirement-2026-08-25.md`；其它仍被 BTC-5m 回放和资源审计使用的数据集未被删除。

## 其他数据的判定

当前仓库只发现两份 BTC 压缩元数据：一份已完成 `RETIRED` 的 clean_v2 manifest 和一份历史
`PLAN_ONLY` 计划；没有发现其他 dataset 同时具备“输出、逐源清单、完整校验、消费者切换和删除后回放
证据”的退役包。因此其它目录当前均为 `RETAIN/UNKNOWN`，不能自动删除。

特别是 raw provider payload、PIT 数据、execution ledger、失败证据和仍被脚本读取的
规范化数据，即使存在相似副本，也必须保留，除非另外完成本约束要求的 cutover。

## 后续执行边界

对每个其他 dataset，先生成 inventory/plan 和角色分类；只有完整通过约束中的拒绝条件检查，
才建立精确的退役清单。发现未知来源、引用、schema、PIT 或恢复风险时，保留源数据并标记
`UNKNOWN`，不以节省空间为理由冒险删除。
