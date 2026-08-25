from scripts.evidence_readiness_audit import audit


def test_audit_fails_closed_without_strict_pit_or_quote_artifacts(monkeypatch, tmp_path):
    monkeypatch.setattr("scripts.evidence_readiness_audit.store.dataset_contracts", lambda: {
        "daily_bars": {"strict_historical_pit": False},
        "fundamentals": {"strict_historical_pit": False},
    })
    monkeypatch.setattr("scripts.evidence_readiness_audit.store.coverage", lambda dataset: {
        "dataset": dataset.name, "symbols": 0, "rows": 0,
    })
    result = audit(data_root=tmp_path)
    assert result["promotion"] == "BLOCKED"
    assert result["gates"]["strict_historical_pit"]["status"] == "UNKNOWN"
    assert result["gates"]["survivorship_control"]["status"] == "UNKNOWN"
    assert result["gates"]["historical_executable_quotes"]["status"] == "UNKNOWN"


def test_audit_does_not_treat_current_universe_file_as_survivorship_evidence(monkeypatch, tmp_path):
    (tmp_path / "discovered_equity_universe.json").write_text("{}")
    monkeypatch.setattr("scripts.evidence_readiness_audit.store.dataset_contracts", lambda: {
        "daily_bars": {"strict_historical_pit": True},
        "fundamentals": {"strict_historical_pit": True},
    })
    monkeypatch.setattr("scripts.evidence_readiness_audit.store.coverage", lambda dataset: {
        "dataset": dataset.name, "symbols": 1, "rows": 1,
    })
    result = audit(data_root=tmp_path)
    assert result["gates"]["strict_historical_pit"]["status"] == "READY"
    assert result["gates"]["survivorship_control"]["status"] == "UNKNOWN"
    assert result["promotion"] == "BLOCKED"
