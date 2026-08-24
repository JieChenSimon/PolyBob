# BTC 5m statistical audit

结论：**UNKNOWN**。正收益不等于可推广；当前门禁必须保持 UNKNOWN。

- 事件数：2506；独立日期：13；独立月份：1
- 聚类 t：34.655；wild bootstrap p：0.0005；p floor：0.000244140625
- 多重检验：255 trials；t hurdle：4.2033

## 门禁

- cluster_inference: UNKNOWN
- wild_bootstrap: UNKNOWN
- date_train_validation_test: UNKNOWN
- month_train_validation_test: UNKNOWN
- oos_stability: UNKNOWN
- drawdown: UNKNOWN
- return_target: UNKNOWN

## 缺失/降级

- event report stores date, not an exact decision timestamp; ordering is date plus entry price
- month split is unavailable until at least three independent months exist, and return targets need twelve complete months
- wild bootstrap p is reported but cannot override the cluster floor or unresolved p resolution
- drawdown has no pre-registered BTC threshold and is not a fill-accurate portfolio curve

## 判定原则

日期与月份均按独立日历标签切分，先切分再做聚类推断；任何分区少于 20 个独立簇均为 UNKNOWN。wild bootstrap、正均值和正 OOS 均不能绕过该门禁。
