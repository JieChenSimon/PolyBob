# PB-0040 cross-sectional snapshot baseline

Date: 2026-08-25

## Snapshot identity

The isolated US-equity replay now records a deterministic identity for the
actual input series consumed by the SimulationService. This prevents silently
comparing a refreshed local universe with an older OOS result.

- Data snapshot SHA-256:
  `e209f21be19b72e19e317586a4eb2557ff71a0acba588fc3c61b6d1ea5f3f63e`
- Discovery manifest SHA-256:
  `802cb3e9e642ecdff377f6cd139acf0a8ad46c14e766cb0d605deace47cbb27f`
- Instruments: 27
- OOS window: 2025-02-14 through 2026-08-24
- Real kernel: `modules.simulation.SimulationService`

## Frozen baseline result

- Signal: lookback 20, top 30%, rebalance 5 sessions
- Risk policy: `vol_target_10`
- Stop-loss: 10%; cooldown: 5 bars
- Mean per-instrument return: 6.329%
- Median per-instrument return: 2.503%
- Positive instruments: 16/27
- Stable instruments: 13/27
- Target-gate passes: 0/27
- Promotion: `BLOCKED` (historical executable depth and research gates)

The machine-readable run was `/tmp/polybob_us_snapshot_baseline_20260825.json`.
This is a research snapshot, not a promotion artifact; the full source data and
manifest remain subject to the existing PIT and executable-depth gates.

## Contract change

`cross_sectional_standalone_replay.py` now records the hash of every consumed
symbol/date/close series, per-symbol row counts and boundaries, plus the
discovery-manifest hash. A changed local refresh therefore creates a visibly
different experiment identity instead of silently invalidating a comparison.
