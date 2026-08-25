# PolyBob cross-domain strategy gate audit

Date: 2026-08-25

## Objective status

No current strategy has passed the user's per-instrument target of at least 50%
annualized return and at least 15% in every complete month. No strategy is
authorized for live promotion. This is an evidence audit, not a claim that
future data can never contain an edge.

## Domain-by-domain evidence

| Domain / strategy family | Real-kernel evidence | Main failure | Status |
|---|---|---|---|
| BTC 5m direction proxy | 3 thresholds, 36 cost/OOS scenarios; total returns about -97.6% to -99.1% | extreme turnover, fees, no net directional edge | `NO_EDGE` |
| BTC 5m dual-MA momentum | 3 pre-registered pairs × 3 cost multiples; best full return -3.32%, best OOS +0.11% | short history, cost sensitivity, depth unknown | `NO_EDGE/UNKNOWN` |
| Major/altcoin TSMOM | 4 walk-forward folds, 18 instruments | only 2/4 folds positive; latest fold negative; depth unknown | `BLOCKED` |
| A-share daily momentum | 8 instruments, strict OOS | all 8 OOS returns negative; PBO 0.9524 | `NO_EDGE/BLOCKED` |
| US cross-sectional momentum | 27 isolated instruments, strict OOS | positive mean is tail-driven; all target gates fail; depth unknown | `BLOCKED` |
| US drawdown recovery | 27 paired instruments | recovery mechanism worsened mean return and drawdown | `NO_EDGE` |
| SEC insider event strategy | real kernel, two cost-aware candidates | 3.89%–4.74% total; no per-instrument target or promotion gates | `BLOCKED` |
| Deep drawdown rebound | row-level quality replay | global PIT/survivorship/depth gates UNKNOWN; too few complete OOS events | `UNKNOWN_NO_EDGE_EVIDENCE` |

## Common failure attribution

1. The requested return target is materially higher than the observed
   cost-after-OOS edge. Positive aggregate results are concentrated in a small
   number of tail instruments and do not generalize to every instrument.
2. Short histories and too few independent calendar clusters prevent reliable
   annual/monthly inference. `UNKNOWN` is retained wherever the evidence is
   insufficient; it is never converted to zero or PASS.
3. Historical executable quote/depth linkage is missing for the replayed stock,
   crypto and event strategies. Midpoint or close-price fills are diagnostics,
   not proof of live tradability.
4. Risk controls can hide the signal rather than improve it: the old drawdown
   policy permanently locked out, while the explicit recovery policy resumed
   trading but reduced paired performance.

## Next executable research actions

1. Freeze each experiment's data snapshot and manifest hash before selection;
   never compare runs whose discovery universe or local bars changed silently.
2. Materialize point-in-time fundamentals and historical quote/depth evidence for
   a small, auditable universe. Until those contracts are READY, preserve
   `BLOCKED` and do not scale any positive tail result.
3. For US cross-sectional momentum, run a genuinely out-of-time walk-forward on
   a newly extended calendar, with the 20/30/5 candidate frozen before the new
   period; report per-instrument monthly target and benchmark-relative returns.
4. For crypto, extend independent calendar coverage before any new parameter
   search; retain the current TSMOM and BTC-5m candidates as frozen baselines.
5. For A shares and deep drawdown events, prioritize trading-calendar,
   point-in-time quality and T+1/limit constraints rather than more momentum
   tuning.

## Gate decision

Promotion Board: **0 trade permissions for these candidates**. The system may
continue paper monitoring and data collection, but no result in this audit is a
verified money-making strategy or evidence for the 50%/15% target.
