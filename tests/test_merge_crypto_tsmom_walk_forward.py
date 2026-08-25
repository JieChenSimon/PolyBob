import json

import pytest

from scripts.merge_crypto_tsmom_walk_forward import merge


def _report(path, split, grid=None, symbols=2):
    path.write_text(json.dumps({
        "candidate_grid": grid or [{"lookback": 60}],
        "symbols": symbols,
        "execution_kernel": "SimulationService",
        "execution_config": {},
        "quality_rejected": 0,
        "folds": [{"split_date": split}],
        "oos_execution_capital": "fresh_initial_capital_per_symbol_and_fold",
    }))


def test_merge_sorts_and_rejects_duplicate_folds(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    _report(a, "2025-01-01")
    _report(b, "2026-01-01")
    result = merge([b, a])
    assert [fold["split_date"] for fold in result["folds"]] == ["2025-01-01", "2026-01-01"]
    _report(b, "2025-01-01")
    with pytest.raises(ValueError, match="duplicate fold"):
        merge([a, b])
