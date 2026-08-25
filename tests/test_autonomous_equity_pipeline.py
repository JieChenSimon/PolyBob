from __future__ import annotations

import json

from scripts import autonomous_equity_pipeline as pipeline


def test_refresh_universe_writes_final_manifest_and_keeps_unknown(monkeypatch, tmp_path):
    calls = []
    initial = {
        "counts": {"total": 2, "ready_for_research": 1, "unknown": 1},
        "provider_errors": {},
        "candidates": [],
    }
    final = {
        "counts": {"total": 2, "ready_for_research": 2, "unknown": 0},
        "provider_errors": {},
        "candidates": [],
    }

    def fake_discover(**kwargs):
        calls.append(kwargs)
        return initial if len(calls) == 1 else final

    monkeypatch.setattr(pipeline, "discover_equity_candidates", fake_discover)
    monkeypatch.setattr(
        pipeline,
        "warm_batch",
        lambda manifest, **kwargs: {"domain": kwargs["domain"], "processed": 1},
    )
    output = tmp_path / "universe.json"
    result = pipeline.refresh_universe(
        domains=("us_equity",), output=output, warm_symbols_per_domain=1,
    )

    assert result["initial_counts"]["unknown"] == 1
    assert result["final_counts"]["ready_for_research"] == 2
    assert result["warm"] == [{"domain": "us_equity", "processed": 1}]
    assert json.loads(output.read_text())["counts"]["unknown"] == 0
    assert all(call["domains"] == ("us_equity",) for call in calls)
