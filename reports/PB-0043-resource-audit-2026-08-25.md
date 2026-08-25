# PB-0043 回放资源与关闭审计（2026-08-25）

## 审计范围

使用 `data/datasets/parts/btc_1m_bars_clean_v2/symbol=BTC-USDT` 的真实本地
BTC-USDT 1 分钟数据，取连续排序后的 600 条记录，通过真实
`SimulationService` 成交、持仓、权益和账本路径运行。该审计验证运行安全，不把
收益结果当作策略证据。

## 结果

| 项目 | 结果 |
|---|---:|
| 状态 | PASS |
| worker 数 | 1 |
| 处理记录 | 600 |
| 成交/平仓 | 60 / 30 |
| 进程 CPU / 墙钟 | 30.16% |
| 吞吐 | 777.57 rows/s |
| 权益采样点 | 25 |
| 关闭异常 | 无 |
| SQLite/WAL/SHM 残留 | 0 |

CPU 指标的范围是单进程审计；多 worker 研究回放仍通过脚本硬上限、数值库单线程
和进度文件约束，不能将本次单进程结果误称为全机 CPU 证明。原始结果保存在
`data/simulation_resource_audit.json`。

## 发现与修复

首次运行暴露审计脚本使用了未注册的 `resource_audit` 策略 ID，服务拒绝启动；已
改为系统支持的 `signal_fusion`，并在失败路径保留 `finally: service.stop()` 和
临时数据库清理。修复后重新运行通过，且没有把第一次失败结果纳入资源结论。

## 基准对比

同一 600 条真实数据和同一成交内核下，每条记录写权益的 baseline 耗时 4.5853s、
600 个权益点；每 25 条采样的优化路径耗时 0.7716s、25 个权益点，墙钟加速约
5.943x。最终权益差为 0，成交数和显式成本完全一致，说明减少权益观察写入没有
改变成交/费用/账本结果；逐笔成交、费用和审计仍保留。

## 当前门禁

- 资源预算和正常关闭：本审计 PASS。
- 磁盘/SQLite 优化的受控基准对比：本轮 PASS，但仍只代表该 600 行单进程审计。
- 分段 checkpoint 恢复与临时库清理：`tests/test_btc5m_simulation_kernel_replay.py` 已覆盖
  可恢复分段、完整结算和 `.checkpoint.json`/SQLite 清理；实际方向回放的 36 个场景也
  已完成并保留 progress/ETA 证据，临时目录无残留。
- 服务重启恢复：`tests/test_simulation.py::test_restart_recovery_resumes_runs_and_positions`
  已覆盖持仓/运行状态恢复。

这些证据覆盖了当前回放路径的异常恢复、正常关闭和大批量分段清理；更高规模的
多域并行压测仍应作为后续容量基线，不把它混入本次策略收益结论。
