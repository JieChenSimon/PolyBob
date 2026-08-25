# Constraint Write Audit

## 2026-08-12T06:50:00Z

- proposal_ref: user-request-project-task-tracker
- approved_item_ids: task-system-integrity
- destinations: `.ai/constraints/index.md`, `.ai/constraints/constraints/task-system-integrity.md`
- operation: create
- status: approved-by-explicit-request
- notes: 用户明确要求为 PolyBob 建立结合 Git 的精密待办追踪系统。

## 2026-08-12T06:50:00Z

- proposal_ref: user-clarification-token-lean-visual-task-tracker
- approved_item_ids: task-system-integrity-minimal-fields-and-visual-state
- destinations: `.ai/constraints/constraints/task-system-integrity.md`
- operation: update
- status: approved-by-explicit-request
- notes: 用户要求少 token、准确、简练、易懂、科学，并强化可视化和状态追踪。

## 2026-08-12T07:05:00Z

- proposal_ref: user-autonomous-trigger-stop-rollback
- approved_item_ids: task-auto-trigger-and-safe-control
- destinations: `.ai/workflows/workflows/task-lifecycle.md`, `.ai/constraints/constraints/task-system-integrity.md`
- operation: update
- status: approved-by-explicit-request
- notes: 非微小开发由 Codex 自主触发；终止不改代码，回滚必须预览、显式确认且 fail-closed。

## 2026-08-12T07:20:00Z

- proposal_ref: user-task-git-commit-push-recovery
- approved_item_ids: task-git-operations-safety
- destinations: `.ai/workflows/workflows/task-lifecycle.md`, `.ai/constraints/constraints/task-system-integrity.md`
- operation: update
- status: approved-by-explicit-request
- notes: 增加显式路径 commit、校验 push、Git doctor、安全修复和未完成操作终止能力。

## 2026-08-12T07:45:00Z

- proposal_ref: user-branch-decision-neutral-naming
- approved_item_ids: branch-decision-and-neutral-naming
- destinations: `AGENTS.md`, `.ai/workflows/workflows/task-lifecycle.md`, `.ai/constraints/constraints/task-system-integrity.md`
- operation: update
- status: approved-by-explicit-request
- notes: 自动决策复用/新建/发布分支；新分支禁止代理或产品品牌词，main 发布仅限显式 fast-forward。

## 2026-08-12T08:00:00Z

- proposal_ref: user-kronos-reference-exclusion
- approved_item_ids: kronos-external-reference-boundary
- destinations: `.git/info/exclude`, `.ai/constraints/constraints/task-system-integrity.md`
- operation: update
- status: approved-by-explicit-request
- notes: Kronos 是用户单独 clone 的参考仓库，不参与 PolyBob 的追踪、修改、提交、推送、回滚或测试。

## 2026-08-12T08:15:00Z

- proposal_ref: user-rename-expanded-control-system
- approved_item_ids: development-control-naming
- destinations: CLI、API、dashboard、workflow、constraints、tests、documentation
- operation: rename
- status: approved-by-explicit-request
- notes: 系统正式命名为 PolyBob Development Control；tasks/PB/trailer 作为兼容数据协议保留。

## 2026-08-12T08:30:00Z

- proposal_ref: user-uv-migration-no-regression
- approved_item_ids: python-environment-reproducibility-and-compatibility
- destinations: `.ai/constraints/constraints/python-environment-integrity.md`, `.ai/constraints/index.md`
- operation: create
- status: approved-by-explicit-request
- notes: 用户明确要求以 uv 替代 Conda、提高迁移性，并保证切换不影响项目行为。

## 2026-08-12T09:00:00Z

- proposal_ref: user-uv-functional-and-dependency-audit
- approved_item_ids: direct-dependency-usage-evidence
- destinations: `.ai/constraints/constraints/python-environment-integrity.md`, `tests/test_python_environment.py`
- operation: update
- status: approved-by-explicit-request
- notes: 用户要求核验全部功能、删除真实冗余依赖，并防止直接依赖和传递依赖继续漂移。

## 2026-08-23T19:42:02Z

- proposal_ref: user-polybob-complete-system-requirements
- approved_item_ids: product-research-data-paper-ui-continuation-integrity
- destinations: `.ai/constraints/index.md`, `.ai/constraints/constraints/product-and-research-integrity.md`
- operation: create
- status: approved-by-explicit-request
- notes: 汇总用户对真实数据、量化证据、模拟盘、前端工作台、任务持续推进和安全边界的硬要求；收益目标被转译为必须验证正期望、未证明则 UNKNOWN，不构成盈利保证。

## 2026-08-24T15:24:00Z

- proposal_ref: user-explicit-per-instrument-return-floor
- approved_item_ids: per-instrument-annual-50-monthly-15-return-gate
- destinations: `.ai/constraints/constraints/product-and-research-integrity.md`
- operation: update
- status: approved-by-explicit-request
- notes: 用户明确要求每个标的年化收益至少 50% 且每月收益至少 15%；作为同时满足的实盘候选验收门槛，不作为盈利保证，未达标必须拒绝晋级并保留证据。

## 2026-08-25T00:00:00+08:00

- proposal_ref: user-requirements-traceability-and-ux-skill-refresh
- approved_item_ids: requirement-evidence-traceability-link
- destinations: `docs/USER_REQUIREMENTS_TRACEABILITY_2026-08-25.md`, `.ai/constraints/constraints/product-and-research-integrity.md`
- operation: create-and-link
- status: approved-by-explicit-request
- notes: 用户要求记录全部系统需求、连接任务看板并核对完成状态；需求文档不替代 Development Control 或 Git 事实源。

## 2026-08-25T00:00:00+08:00

- proposal_ref: user-agent-team-scope-correction
- approved_item_ids: bounded-agent-team-and-single-agent-default
- destinations: `.ai/constraints/constraints/product-and-research-integrity.md`
- operation: create
- status: approved-by-explicit-request
- notes: 用户明确要求由主 Agent 判断是否需要团队；默认单 Agent，必要时最多 3 个，避免机械并行和重复审查。

## 2026-08-25T03:15:00+08:00

- proposal_ref: user-local-resource-budget-and-judgment
- approved_item_ids: bounded-multicore-research-with-60-percent-cpu-budget
- destinations: `.ai/constraints/constraints/product-and-research-integrity.md`
- operation: create
- status: approved-by-explicit-request
- notes: 用户要求研究任务合理使用多核，但总 CPU 不超过 60%；正常运行不自动停止，需根据实际资源和系统影响判断是否调整并发。

## 2026-08-25T03:30:00+08:00

- proposal_ref: user-explicit-all-instruments-validation
- approved_item_ids: asset-domain-instrument-strategy-matrix
- destinations: `.ai/constraints/constraints/product-and-research-integrity.md`
- operation: create
- status: approved-by-explicit-request
- notes: 用户明确要求不能只测试 BTC 5 分钟；A 股、美股、BTC 和山寨币的每一个标的都必须逐一完成真实数据、成本后、样本外、收益目标和风险门禁验证，结果不得跨标的外推。

## 2026-08-25T04:20:00+08:00

- proposal_ref: user-small-file-and-log-lifecycle-governance
- approved_item_ids: layered-dataset-small-file-compaction-cache-ttl-and-structured-log-retention
- destinations: `.ai/constraints/constraints/product-and-research-integrity.md`, `tasks/items/PB-0044.yml`
- operation: create
- status: approved-by-explicit-request
- notes: 用户要求盘点大量小文件、识别数据/缓存/临时物/日志来源，按专业标准合并压缩去重并治理重复日志；保留原始证据、PIT、manifest 和审计账本，禁止未经校验的宽泛删除。

## 2026-08-25T05:30:00+08:00
- proposal_ref: user-autonomous-drawdown-universe-discovery
- approved_item_ids: training-window-candidate-discovery-and-domain-specific-applicability
- destinations: `.ai/constraints/constraints/product-and-research-integrity.md`, `reports/PB-0040-probe-and-universe-2026-08-25.md`
- operation: create
- status: approved-by-explicit-request
- notes: 用户要求系统自主发现 A 股、美股和加密标的，并指出低回撤核心资产不应被强行套用 50% 深回撤策略；新增训练窗口冻结、OOS 禁止反选和分层适用性约束。

## 2026-08-25T00:00:00+08:00

- proposal_ref: user-safe-delete-compressed-source-data
- approved_item_ids: classify-before-delete; verified-compaction-replacement; consumer-cutover; auditable-exact-retirement; source-retention-when-needed-for-pit
- destinations: `.ai/constraints/index.md`, `.ai/constraints/constraints/data-retirement-and-compaction-integrity.md`
- operation: create-and-link
- status: approved-by-explicit-request
- notes: 用户要求所有数据在压缩后，只要不影响使用和系统运行就删除原数据；新增分类、完整替代物、消费者切换、PIT/审计保留、精确删除和删除后验证门禁。当前仅已完成验证的 BTC-1m 源树具备退役证据；其他未建立完整 manifest 的数据不得自动删除。

## 2026-08-25T00:00:00+08:00

- proposal_ref: user-all-datasets-share-safe-retirement-rule
- approved_item_ids: universal-dataset-compaction-retirement-scope; compression-success-is-not-delete-authorization
- destinations: `.ai/constraints/constraints/data-retirement-and-compaction-integrity.md`
- operation: update
- status: approved-by-explicit-request
- notes: 用户明确要求所有其他数据同样执行压缩后源数据退役规则；扩展适用范围到所有数据集，并明确压缩成功本身不授予删除权限，未完成证据链的数据必须保留并标记 UNKNOWN。
