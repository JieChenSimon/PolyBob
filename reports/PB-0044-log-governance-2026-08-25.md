# PB-0044 日志治理与关闭证据（2026-08-25）

## 现有策略

1. 应用使用 structlog，`LOG_FORMAT=auto` 在终端输出 console、非交互环境输出
   JSON；默认写 stderr，不创建无界应用日志文件。
2. 盘口原始事件日志默认关闭。开启后由 `BookEventLog` 写入 SQLite WAL，内存
   buffer 有上限，批量 flush，`POLYBOB_BOOK_LOG_RETENTION_DAYS` 和
   `POLYBOB_BOOK_LOG_MAX_ROWS` 同时限制保留量，最多每小时 prune 一次。
3. 原始盘口事件（book/price_change/last_trade_price）不做抽样，因为它是确定性
   replay 的审计输入；超过 buffer 上限时只丢弃 raw-log 记录并计数，不阻塞实时
   ingest，也不影响规范化盘口状态。
4. 研究回放的诊断日志只保留 WARNING/ERROR，逐笔成交仍进入账本；进度和 ETA
   单独写入有界 JSON 文件，临时 SQLite/WAL/SHM 在关闭或 checkpoint 完成后清理。

## 已验证的关闭与恢复

- `tests/test_book_platform.py` 验证原始事件批量写入、读取和 replay 确定性。
- `tests/test_simulation.py` 的服务重启测试验证运行和持仓恢复。
- `tests/test_btc5m_simulation_kernel_replay.py` 验证分段 checkpoint、完整结算、
  checkpoint 和临时 SQLite 清理。
- PB-0043 资源审计验证服务关闭后无 WAL/SHM 残留；完整回归当前为
  `1155 passed, 5 skipped, 10 deselected`。

## 保留边界

本报告不把外部浏览器工具的 `.playwright-cli` console 文件当作 PolyBob 业务日志，
也不擅自删除它们。应用侧没有无界文件日志轮转需求；若未来启用文件日志，必须
显式配置大小/时间轮转、压缩、保留天数和关闭 flush，并补充恢复测试。

当前 PB-0044 的日志结构化、保留/采样/关闭证据已具备；精确内容去重与全数据迁移
切换仍未完成，未知 provenance 不删除。
