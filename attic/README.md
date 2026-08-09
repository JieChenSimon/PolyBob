# attic — 隔离区,不是垃圾桶

这里的代码**零引用**:没有任何 `apps/`、`libs/`、`services/`、`scripts/` 或测试
import 它们。移到这里而不是直接删掉,是因为"零引用"和"没用"不是一回事——
可能是某个还没接线的想法。

规则:
- 在这里待满一个季度、期间没人来取,就可以删。
- 要复活某个模块,把它移回原位并**同时**加上调用方和测试。
  没有调用方的复活等于把它再送回来一次。
- 这个目录不参与测试、不参与 CI、不参与 import。

## 移入记录

### 2026-08-09 — 架构收缩第 0 阶段

**services/(3 个,零引用)** —— 这三个从来没有被任何东西调用过:
- `ai_orchestrator` `api_server` `trading_engine`

**strategies/(6 个,零引用)** —— 宽扫时代的产物,没有一个通过门禁:
- `ai_enhanced_strategy` `ai_predictor` `cross_market_strategy`
- `enhanced_contract_strategy` `enhanced_stat_arb` `hybrid_strategy`

**libs/quant/(5 个,零引用)**:
- `position_sizing` `portfolio_optimization` —— 仓位/组合优化写好了但从没接线。
  **注意**:这两个是要回来的,在第 3 阶段(组合账本)。它们不是废code,
  是缺了地基的code——没有真实持仓和现金,Kelly 公式无处可用。
- `statistical_tests` `cointegration_enhanced` `garch_enhanced`

### 2026-08-09 — 前端收缩(第 4 阶段)

**apps/dashboard/app/(4 个页面)** —— 它们服务的是一个不存在的交易台:
- `execution` `simulation` `risk-ops` `strategies`

可开仓的边是 **0 条**。一个执行台、一个模拟盘、一个风险运营台和一个策略中心,
加起来给零条策略提供操作界面 —— 页面的*形状*是一种承诺,把数字清空并不能收回它。
记分牌(哪些边通过了门禁)和降级原因现在都在 `/overview` 上,那是它们该在的地方。

要复活其中任何一个,前提是先有一条通过门禁的边需要它。
