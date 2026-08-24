# PB-0040 逐标的真实数据策略矩阵回放

## 结论

本轮对本地真实 `daily_bars` 中用户指定的 43 个可用标的逐一完成了模拟盘内核回放：A 股 8 个、美股 26 个、加密资产 9 个（包含 BTC-USDT 和 8 个山寨币）。结果为 **43/43 FAIL，0 个标的通过 Promotion 门禁**。这不是把缺失数据或未运行写成失败：43 个标的均实际完成了回放；失败原因按标的保留在 `data/simulation_research_matrix_report.json`。

Promotion 仍为 BLOCKED。年化 50% 和完整月份 15% 的目标没有任何标的取得可验证证据，因此不能据此开启真实交易或声称策略能够赚钱。

## 分域结果

| 资产域 | 实际回放 | PASS | FAIL | 主要失败模式 |
|---|---:|---:|---:|---|
| A 股 | 8 | 0 | 8 | OOS 非正/稳定性不足、闭合交易不足、PBO 超门槛 |
| 美股 | 26 | 0 | 26 | 成本后收益和 OOS 非正、PBO/稳定性失败、回撤或交易数门禁 |
| 加密资产 | 9 | 0 | 9 | PBO 超门槛、部分标的 OOS/全样本非正、稳定性不足 |

代表性成本后全样本收益：A 股 600519 为 -2.22%、000001 为 +0.52%、300750 为 +2.52%；美股 AAPL 为 -3.60%、NVDA 为 +3.38%、AMD 为 +6.51%；加密 DOGE-USDT 为 +11.61%、XRP-USDT 为 +9.96%、BTC-USDT 为 +1.00%。这些正收益仍因 OOS、稳定性、PBO 或交易样本门禁失败，不能视为可靠优势。

## 专业判断

1. 分域校准选出的候选不能转化为跨标的优势。每个标的单独做了 full replay，所有结果单独判定，没有用 BTC-5m 或某个赢家代表其他标的。
2. “看起来赚钱”的标的仍然不够。当前证据缺少稳定的样本外正收益，且多重检验概率失败；短样本和候选选择会放大过拟合风险。
3. 目标收益不是调参理由。50% 年收益、完整月份 15% 只能作为硬门禁，不能通过放宽成本、忽略滑点、跨资产迁移或增加参数搜索来制造达标结果。
4. 下一轮应优先补充各标的更长 PIT 历史、真实交易时段/流动性与可成交报价，并把交易成本、容量、持有期、月度收益和风险预算纳入预注册候选；失败标的保持 BLOCKED/NO_EDGE。

## 可复现证据

- 原始矩阵：`data/simulation_research_matrix_report.json`
- 命令：
  `uv run --locked python scripts/simulation_research_pipeline.py --symbols '<configured symbols>' --optimization-symbols 8 --report data/simulation_research_matrix_report.json`
- 验证：`tests/test_simulation_research_pipeline.py` 7 passed；脚本编译通过；`dev_control validate` 为 `OK 43 tasks`。
- 后续回放进度文件：`data/simulation_research_progress.json`。它记录阶段、已完成回放数、总数、耗时、ETA、当前标的和更新时间；本次矩阵是在该进度机制加入前完成，因此本报告的历史运行没有伪造进度数据。
