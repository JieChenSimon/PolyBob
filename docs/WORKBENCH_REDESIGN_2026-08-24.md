# PolyBob 专业工作台改版基线

## 标的终端框架 — 2026-08-24

美股、A股、加密现货和 BTC 5m 现在共享专业标的终端框架：选中标的上下文、紧凑市场头部、左侧标的队列、中心研究/行情区域，以及右侧研究与风险 dock。借鉴的是专业工作台的信息架构，不复制杠杆诱导或交易权限。

设计参考 Hyperliquid 官方文档中的订单簿上下文、订单/持仓关系、图表上的 TP/SL 交互和组合图表分层；PolyBob 继续保留自己的 fail-closed 研究门禁，研究页面不会暗示执行权限。

## 目标

PolyBob 借鉴 Hyperliquid 的市场级信息密度、IBKR Mosaic 的联动工作区、Coinbase Advanced 的图表/盘口/订单组合，但不复制高杠杆交易诱导。产品主线保持：

`证据 → 决策 → 风险 → Paper intent → 成交事实 → 复盘`

## 页面契约

| 路由 | 唯一职责 | 首屏核心结论 |
|---|---|---|
| `/overview` | Daily Brief | 今天先复核什么、什么被阻塞 |
| `/markets` | Market Triage | 哪些市场值得进一步观察 |
| `/equities` | Equity Observation | 当前标的行情和数据可信度 |
| `/strategies` | Strategy Control | 哪些策略有证据、能否产生信号 |
| `/execution` | Paper Execution | intent/order/basket 状态和风险门禁 |
| `/risk-ops` | Risk Operations | 组合、数据、服务和对账异常 |
| `/settings` | Runtime Boundaries | provider、账户、Lab 和系统边界 |

旧的 `/us-equities`、`/journal`、`/polymarket`、`/crypto`、`/dev-control` 保留为兼容或专用入口，不再与 Core 主导航争夺同一层级。

## 统一状态模型

页面不得只显示一个数字判断系统是否正常。核心 read model 需要能够表达：

- `state`: available / degraded / unknown / blocked / disabled
- `source`: provider、ledger 或计算来源
- `observed_at`: 观测时间
- `reason`: 不可用、过期或阻断原因

关键不变量：`unknown != safe`、`cached != realtime`、`promoted != guaranteed`、`filled != profitable`。

## 工作区交互

- 桌面端使用紧凑状态条、队列、选中详情和时间线。
- 选中标的应成为图表、研究、信号和 Paper intent 的共享上下文。
- 移动端优先显示选中对象和结论，再用 Queue/Detail 分段切换。
- Lab、Archive 和 Core 使用明确的路由、标签和权限文案隔离。
- 用户偏好只保存视图、筛选器和图表配置；不静默保存执行授权、金额或风险阈值。

## 来源

- [Hyperliquid Trading](https://hyperliquid.gitbook.io/hyperliquid-docs/trading)
- [Hyperliquid Order Book](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/order-book)
- [Hyperliquid TP/SL](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/take-profit-and-stop-loss-orders-tp-sl)
- [IBKR TWS](https://www.interactivebrokers.com/en/trading/tws.php)
- [IBKR Mosaic QuickStart](https://www.interactivebrokers.com/en/trading/tws-quickstart.php)
- [Coinbase Advanced Dashboard](https://help.coinbase.com/coinbase/trading-and-funding/advanced-trade/dashboard-overview)

本文件是产品设计合同，不代表 PolyBob 已具备真实交易所执行能力；实时 provider、Paper Broker 和 canonical ledger 仍按能力矩阵独立验收。
