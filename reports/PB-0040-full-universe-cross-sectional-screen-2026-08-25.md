# PB-0040 全量自主发现宇宙横截面 screen（2026-08-25）

## 范围

本轮使用完整自主发现 manifest，而不是此前限额的 41 个标的：

- A 股：55 个 READY 标的全部进入 screen。
- 美股：1,364 个 READY 标的中 202 个因本地价格序列存在未解析跳变被拒绝，
  1,162 个进入 screen。
- 加密资产：完整 manifest 不包含加密标的，保持独立 crypto 数据管线，未混入
  股票横截面。

每个域都测试 54 个预注册组合（lookback 20/30/60、top fraction 20%/30%、
rebalance 1/5/10 日、raw/vol-target/drawdown 风控），候选只按训练期超额选择，
OOS 没有参与选参。

## 结果

### A 股

训练期最佳为 `lookback=20, top_frac=0.2, rebalance=5,
risk_policy=vol_target_10_dd`，训练超额 `+35.63%`；但 OOS 收益
`-9.12%`，相对等权基准超额 `-2.98%`，因此没有晋级。

### 美股

54 个组合中没有一个训练期超额为正，故没有候选被送入 Paper Lab。最好的训练
结果仍为 `-6.97%` 超额；表面上若直接看 OOS，部分组合为正，但对应的等权
基准约 `+1861.70%`，且滚动超额不稳定，不能把绝对正收益当作 alpha。该基准
异常高也说明美股全量宇宙仍需要进一步的复权、拆并股和生存偏差审计。

## 决策

全量自主发现扩大了覆盖面，但没有发现可通过训练期门禁的横截面候选。A 股
候选在 OOS 反转为负，美股未形成训练期优势；本轮不启动全量 Paper Lab 盲目
回放，也不 Promotion。下一步优先修复美股价格基准/拆并股和 survivorship
审计，并对 202 个被拒标的保留具体拒绝原因；修复后重新做固定样本外 screen。

## 可复现产物

- 输入：`data/discovered_equity_universe_full.json`
- 运行输出：`/tmp/polybob_full_cross_sectional_screen.json`
- 运行器：`scripts/cross_sectional_local_screen.py`
- 真实数据、成本后、训练选择与滚动折叠结果均保存在运行输出中。
