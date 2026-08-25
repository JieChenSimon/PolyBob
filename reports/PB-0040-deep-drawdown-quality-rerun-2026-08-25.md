# PB-0040：真实 SEC 质量过滤深度回撤策略重放

## 结论

本轮修复了 SEC PIT 数据物化中的真实完整性问题，并在修复后的本地缓存上重新运行了 48 个真实模拟盘 case。结果仍不能晋级：只有 AMD 有 1 个完整 OOS 事件，最长持有期 252 日的 1x 成本 OOS 收益为 3.788%，远低于年化 50% 和每个完整月 15% 的目标；其余标的没有足够的完整 OOS 事件支持收益结论。状态保持 `BLOCKED / NO_EDGE_EVIDENCE`。

## 数据修复

原物化器在 SEC `accepted_at` 缺失时把 filing date 推成午夜 `announcement_at`。日历日期不是可观测公告时间，这会把未知 PIT 数据错误地变成已知。现在缺失时间保留为 `None`，质量门禁 fail closed。修复后用 SEC 缓存中的真实 Company Facts 与 Submissions 数据重新物化 12 个美股标的，12/12 可用，所有物化记录都有真实 `accepted_at`。

## 重放合同

- 标的请求：SNDK、MU、WDC、MRVL、AMD、NVDA、INTC；只允许质量门通过的事件进入交易。
- 触发：首次因果收盘价相对扩张峰值回撤至少 50%。
- 入场：25% probe、5 个交易日确认、固定 0/5/20 日分批。
- 持有期：21、63、126、252 日；成本：1x、2x、3x；单标的 NAV 上限 5%。
- 执行：每个 case 使用真实本地日线与真实 `SimulationService` 成交、持仓、费用、权益和账本路径。
- 资源：逐日合作式节流；进程观测 CPU 保持在 10%–34%，没有超过 60%。

## 逐标的 OOS 结果

| 标的 | 质量事件 | 完整 OOS 事件 | 21 日 1x | 63 日 1x | 126 日 1x | 252 日 1x |
|---|---:|---:|---:|---:|---:|---:|
| MRVL | 通过 | 0 | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| AMD | 通过 | 1 | -0.027% | 2.825% | 2.306% | 3.788% |
| NVDA | 通过 | 0 | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| INTC | 通过 | 0 | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |

SNDK、MU、WDC 没有质量通过事件，因此没有被交易；这不是负收益，也不是 PASS，而是 `UNKNOWN/NO_TRADE`。AMD 的成本压力单调：252 日 OOS 从 1x 的 3.788% 降至 2x 的 3.746%、3x 的 3.677%。

机器可读结果：`data/deep_drawdown_kernel_quality_confirm5-rerun-2026-08-25.json`。

## 研究决策

质量过滤解决了一个数据真实性缺陷，但没有创造可验证收益优势。不能对一个 OOS 事件年化外推，也不能据此满足月度目标。下一步必须补齐历史退市/生存偏差和历史 BBO/深度，达到 READY 后再原样重放；在此之前不继续调 confirmation、分批间隔或持有期参数。
