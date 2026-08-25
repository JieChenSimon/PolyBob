# PB-0040 存储/芯片标的基本面质量过滤复核（2026-08-25）

## 范围

针对用户提出的深回撤反弹场景，选择 SNDK、MU、WDC、MRVL 四个真实本地日线
标的，运行 `deep_drawdown_kernel_replay.py --fundamental-quality-only`。每个标的
测试 21/63/126/252 日持有期和 1×/2×/3× 成本压力，共 48 个真实
`SimulationService` 案例。

基本面过滤只允许事件日期满足已有 PIT 行级质量规则的事件进入模拟盘；缺少接受
时间、收入/利润/现金流/债务字段或存储周期字段时保持 `UNKNOWN_NO_TRADE`。

## 结果

| 标的 | 质量事件放行 | OOS 完整事件 | 交易案例结论 |
|---|---:|---:|---|
| MRVL | 有（事件日期门通过） | 0 | 有交易但全部为样本内，不能评估 OOS |
| SNDK | 0 | 0 | 存储周期字段缺失，全部 UNKNOWN_NO_TRADE |
| MU | 0 | 0 | 基本面字段缺失，全部 UNKNOWN_NO_TRADE |
| WDC | 0 | 0 | 周期字段缺失/质量规则失败，全部 UNKNOWN_NO_TRADE |

MRVL 的质量过滤案例在 1×成本下 21/63/126/252 日总账户收益分别约为
`+1.22%/+3.59%/+2.37%/+4.30%`，但这些收益没有 OOS 完整事件，且历史日线没有
可成交盘口深度，因此不能解释为策略收益，更不接近年化 50%和月度 15%门槛。

## 结论

本轮没有产生可 Promotion 的候选。过滤器成功阻止了在 SNDK、MU、WDC 基本面
信息不完整时自动重仓；MRVL 暴露出“质量通过但 OOS 样本为空”的独立性问题。
下一轮必须补齐存储周期相关的 PIT 财务字段、历史退市/幸存者控制和真实报价/深度，
并等待新的独立回撤事件后再测试。未补齐前，这四个标的均不允许自动交易。

原始证据：
`data/deep_drawdown_kernel_quality_probe.json`；进度文件：
`data/deep_drawdown_kernel_quality_probe.progress.json`。
