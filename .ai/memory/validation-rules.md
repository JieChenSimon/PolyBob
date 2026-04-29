# Validation Rules

- Default validation for this project is `conda run -n polybob python -m pytest -q`.
- Dashboard validation must also include `npm run build` inside `apps/dashboard`.
- Lab modules that are disabled by default must still have tests proving the disabled path and guard behavior.
- Core validation should remain fast enough to run routinely during normal development.
