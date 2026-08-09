# Validation Rules

- Default validation for this project is `conda run -n polybob python -m pytest -q`.
- Dashboard validation must also include `npm run build` inside `apps/dashboard`.
- Lab modules that are disabled by default must still have tests proving the disabled path and guard behavior.
- Core validation should remain fast enough to run routinely during normal development.
- The promotion board has exactly one writer, `scripts/event_study_board.py`. After re-running any experiment, regenerate it (`python scripts/event_study_board.py`) or `tests/test_event_study_board.py` will fail. Never hand-edit `data/promotion_board.json`.
- Live-provider tests are marked `real_data` and excluded from the default run. Run them deliberately before trusting a data path: `pytest -m real_data`.
- A board row with `role: trade` must have a real strategy implementation; the board test enforces it.
