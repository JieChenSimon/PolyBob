# PB-0040 cross-sectional `vol_target_10_dd` lockout audit

Date: 2026-08-25

## Decision

**Reject this risk policy.** The replay used the fixed 20-day / top-30% /
5-day cross-sectional signal and added only the existing
`vol_target_10_dd` policy, a 10% stop-loss and five-bar cooldown. It did not
improve returns: the policy caused all 27 US-equity isolated accounts to have
zero trades during the requested OOS window.

## Evidence

- Real local daily bars and real `modules.simulation.SimulationService`.
- Domain: US equities; 27 quality-accepted instruments, 7 quality rejections.
- OOS window: 2025-02-14 through 2026-08-24.
- Signal: lookback 20, top fraction 30%, rebalance every 5 sessions.
- Risk policy: `vol_target_10_dd`.
- Additional guard: 10% stop-loss, five-bar cooldown.
- All 27 instruments: `trade_count=0`, total return `0.0%`, max drawdown
  `0.0%`, and target gate `FAIL`.
- Promotion remained `BLOCKED` because zero trades provide no edge evidence and
  historical executable depth is unresolved.

## Root cause

The policy sets exposure to zero once portfolio drawdown reaches 20%. In the
full-history causal signal stream, that condition was reached before the OOS
slice and the policy never re-enabled exposure. The OOS replay therefore
measured a permanent risk-off state, not a profitable strategy.

This is an important distinction: zero trades and zero drawdown are not a
successful risk-adjusted result. A risk lockout must expose its state
transition, recovery rule, and time spent inactive; otherwise it can conceal a
failed signal behind a flat equity curve.

## Follow-up

No parameter tuning is authorized for this candidate. If a recovery rule is
researched later, it must be pre-registered (for example, a causal recovery
window or a new high-water mark), evaluated on the same frozen universe and
dates, and compared against the unguarded 20/30/5 candidate with identical
per-instrument capital and costs. It must not be selected from this OOS result.
