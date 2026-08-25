# 数据压缩、替换与源数据退役完整性

## Scope

适用于 `data/` 下的所有数据类型，不限于行情：原始响应、规范化数据、A 股/美股/加密
货币数据、模型输入、特征快照、资金费率/SEC 数据、行情分片、缓存、回放临时物、日志和任何
由压缩/合并生成的新数据集。目标是消除已经被可靠替换的数据所占用的冗余空间，同时
保护可重放性、PIT 真实性、审计账本和故障恢复能力。

本约束由用户明确要求“压缩后在不影响使用和系统运行的前提下删除原数据”而生效。
“压缩后”不等于“可以直接删除”：只有经过下述逐项验证的、可重新生成或已由完整替代物
覆盖的数据，才允许退役。不可变原始证据、PIT 版本、唯一失败证据和审计账本不能仅因
存在压缩副本而删除。

## Hard acceptance criteria

### 1. 先分类，再决定是否可删除

- “所有其他数据也一样”是本约束的默认适用范围：任何数据集都必须经过同一套分类、完整替代物、消费者切换、审计和删除后验证；不能因为文件后缀、来源或数据量不同而跳过门禁。

- 每个候选源路径必须先标记为 `immutable_evidence`、`normalized_replay`、`cache`、
  `temporary` 或 `log`，并记录 dataset、资产域、时间范围、来源和保留级别。
- `cache`、已由完整规范化数据覆盖的 `normalized_replay`、成功结束且无审计价值的
  `temporary`，在通过本约束后可以删除；`immutable_evidence`、PIT 版本、execution
  ledger、唯一失败证据和仍被重放/对账依赖的文件默认必须保留。
- 无法判断用途、来源、PIT 状态或恢复边界时，状态必须为 `UNKNOWN`，不得删除。

### 2. 压缩输出必须是可用的完整替代物

删除前必须有内容寻址的 compaction manifest，至少包含：源文件清单及哈希、源总字节数、
行数、schema fingerprint、instrument/partition/time range、source/observed time、
输出文件清单及哈希、输出行数和字节数、代码版本、run_id 以及 provenance/manifest 引用。

必须验证：

- 输出可被当前查询层、回放器和相关 API 读取；
- 行数、字段语义、主键/去重规则、时间边界和 PIT/provenance 覆盖与源数据一致；
- 需要去重时，去重规则有明确记录，不能把合法重复 observation 静默丢失；
- 输出不依赖已删除的旁车文件、旧 manifest、符号链接或临时目录；
- 在删除前完成一次受影响策略/回放 smoke test 和恢复性读取测试。

### 3. 消费者和运行时必须完成切换

- 静态代码、配置、任务、数据库、manifest 和运行进程引用扫描必须确认没有活跃消费者
  继续写入或读取旧路径；扫描结果和命令必须落盘到验证报告。
- 删除前必须确认没有 writer、collector、worker、SQLite `-wal/-shm`、pending 文件或
  未完成 run；关闭/取消路径必须已经完成资源清理。
- 退役后，采集器和回放器必须写入新的 live/incremental 路径，禁止重建已经退役的旧树；
  必须有回归测试防止旧路径复活。

### 4. 删除必须可审计、精确且可恢复到系统层

- 删除操作必须是 dry-run 后的精确 dataset/path 清单，禁止对 `data/`、仓库根目录或不受
  约束的通配目录做递归删除。
- 删除前必须保存源清单、源哈希、输出哈希、删除原因、操作者/run_id、时间和验证结果；
  活跃 manifest 必须移除失效源引用或把它标为明确的 retired tombstone，不能留下假路径。
- 删除后必须重新运行 inventory，确认目标字节已释放、输出仍可读、manifest 无 stale path、
  查询/回放/审计 smoke test 通过，并记录保留/删除字节数。
- 本地删除不可逆时，只有当输出、manifest、provenance 和可重复获取边界足以支持系统恢复
  才可执行；若需要保留原始 provider payload 才能重建 PIT 或解释历史决策，则不得删除。

### 5. 长期治理

- 新的 compaction 工具默认必须先写 sidecar、校验并保持源数据；源退役必须是单独的、受
  本约束保护的 cutover 步骤，不能由普通压缩命令隐式执行。
- “压缩成功”只代表产生候选替代物，不代表源文件可删除。除非存在独立的、已验证的退役
  清单和删除记录，任何压缩工具都必须保持源数据；未知用途或未完成验证的数据一律保留并标记
  `UNKNOWN`。
- 批量合并应使用有界内存、临时文件原子替换和受控并发，不能因清理而长时间满载 CPU、
  持续高强度读盘或阻塞 API；资源异常时保留源数据并标为 `DEGRADED`/`UNKNOWN`。
- 只有压缩后的完整替代物实际被系统使用且通过稳定运行观察期后，才允许删除源数据；
  观察期内发现 schema、延迟、回放或数据覆盖回归，必须停止退役并恢复使用源数据。

## Rejection conditions

- 只有输出文件存在但没有逐源清单、哈希、行数/schema/PIT/provenance 验证；
- 任何活跃代码、任务或进程仍会读写旧路径；
- 源数据含有唯一原始证据、审计账本、PIT 版本或未迁移的失败证据；
- 输出依赖临时文件、旧 manifest、外部不可追溯状态，或无法独立恢复；
- 发现哈希冲突、行数/时间边界/schema 不一致、重复语义未解释、manifest stale path；
- 未完成 dry-run、回放 smoke test、异常退出清理测试或删除后 inventory；
- 删除目标是宽泛根目录、未解析的 glob 或混合用途目录；
- 资源压力、磁盘错误、并发 writer 或外部数据状态使结果不确定。

## Required validation

至少执行并保留输出：

1. `uv run --locked python scripts/dataset_file_governance.py inventory --root data`；
2. 对候选 dataset 执行 `scripts/compact_dataset_parts.py` 的 plan/dry-run，核对源清单和
   manifest；
3. 静态引用扫描和运行进程/writer 检查；
4. 输出 Parquet/schema/row/time/PIT/provenance 读取校验；
5. 受影响查询、API、回放和任务测试；
6. 精确删除后再次 inventory、manifest stale-path 检查和回放 smoke test；
7. `uv run --locked python scripts/dev_control.py validate` 及相关 pytest。

任何一步没有证据都不能从“候选”升级为“允许删除”。
