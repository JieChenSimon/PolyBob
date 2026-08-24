# PB-0040 深度回撤候选：真实本地数据诊断回放（2026-08-25）

## 结论

本轮把自主发现清单中的 41 个 READY 标的（A 股 8、美股 33）接入真实
Paper Lab 内核，按 4 个持有期（21/63/126/252 日）和 3 档成本压力
（1x/2x/3x）共运行 492 个 case。没有形成可晋级的策略证据，全部保持
`BLOCKED`。这不是把未交易误报为零收益：严格基本面门禁批次明确标记为
`UNKNOWN_NO_TRADE`，未将缺少可验证 PIT 基本面的标的当成亏损样本。

## 两个批次

### 严格基本面质量门禁（补齐 SEC 后复跑）

先用修复后的物化器从自主发现 manifest 中读取 33 个 READY 美股候选；33/33
标的均成功写入 SEC XBRL 基本面，且全部物化行都有真实 `accepted_at`。随后
使用 `--fundamental-quality-only` 完成 492/492 个 case 的 Paper Lab 回放。
严格质量字段（收入、毛利、经营现金流、债务/现金）完整并通过的回撤日期只
出现在极少数标的的训练期（例如 `ABX` 两个日期、`ADMA` 一个日期），没有
任何 OOS 完成事件或 OOS 交易。因此结果仍为 `UNKNOWN_NO_TRADE`，但原因已
从“基本面数据未物化”收敛为“可验证质量日期稀疏且没有 OOS 事件”。

这只能说明当前本地数据无法证明“回撤时基本面未破坏”，不能说明策略收益为
0 或可交易；没有 OOS 样本就不能把训练期通过日期晋级。

### 无基本面门禁的诊断批次

该批次只用于定位价格回撤规则的潜在信号，仍保留 PIT、可执行报价和推广门禁。

- A 股：只有 `000568` 在 21 日持有期产生 1 个 OOS 完成事件，1x 成本净收益
  `-0.31%`；2x/3x 分别约 `-0.37%`/`-0.47%`。
- 美股：16 个 case、21 个 OOS 完成事件在 1x 成本下的 case 平均净收益约
  `+1.13%`；2x 约 `+1.10%`，3x 约 `+1.04%`。
- 单事件最高值为 `ABCL` 126 日约 `+8.70%`、`ABSI` 63 日约 `+6.10%`，
  但事件数量极少，不能据此宣称存在稳定优势。
- 已观察到负收益样本，包括 `ABR` 63 日约 `-1.58%`，以及 `ACHR`、
  `ADMA` 等标的的负事件；成本压力整体使结果变差。

## 专业判断与下一步

当前证据受事件稀疏、严格 PIT 基本面日期缺失、独立 OOS 样本不足限制。
因此不把 `ABCL`/`ABSI` 的单次高收益硬编码为策略，也不把严格门禁的
`UNKNOWN_NO_TRADE` 当成失败收益。下一轮应优先补齐可按公告时间回放的历史
基本面数据，并以事件聚类后的样本外检验、成本后收益、最大回撤和组合层结果
重新评估；在此之前不允许自动晋级或真实下单。

## 可复现产物

- 运行器：`scripts/deep_drawdown_kernel_replay.py`
- SEC 物化器：`scripts/materialize_sec_fundamentals.py`
- 自主发现输入：`data/discovered_equity_universe.json`
- SEC 物化摘要：`/tmp/polybob_sec_materialize_ready.json`（33/33 available，
  33/33 strict PIT candidate）
- 严格批次：`/tmp/polybob_liquid_drawdown_quality.json`
- 补齐 SEC 后复跑：`/tmp/polybob_liquid_drawdown_quality_refreshed.json`
- 诊断批次：`/tmp/polybob_liquid_drawdown_diagnostic.json`
- 进度文件分别为对应的 `*_progress.json`，三批均完成 `492/492`。
