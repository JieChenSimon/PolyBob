from __future__ import annotations

import pandas as pd

from libs.data import universe_discovery as discovery


def test_discovery_marks_missing_history_unknown(monkeypatch):
    monkeypatch.setattr(discovery, "discover_us_roster", lambda: [
        discovery.RosterMember("NEWCO", "us_equity", None, "test")
    ])
    class EmptyFrame:
        def __len__(self): return 0
        def get(self, key, default): return default
    monkeypatch.setattr(discovery.store, "read", lambda *args, **kwargs: EmptyFrame())
    result = discovery.discover_equity_candidates(domains=("us_equity",), min_bars=200,
                                                  min_dollar_volume=5_000_000)
    assert result["counts"] == {"total": 1, "ready_for_research": 0, "unknown": 1}
    assert result["candidates"][0]["status"] == "UNKNOWN"
    assert "bars<200" in result["candidates"][0]["reasons"]


def test_discovery_deduplicates_and_keeps_real_price_basis(monkeypatch):
    monkeypatch.setattr(discovery, "discover_us_roster", lambda: [
        discovery.RosterMember("AAA", "us_equity", None, "test"),
        discovery.RosterMember("AAA", "us_equity", None, "test"),
    ])
    frame = pd.DataFrame({
        "event_date": ["2026-08-25"] * 250,
        "price_basis": ["unadjusted"] * 250,
        "close": [100.0] * 250,
        "volume": [100_000.0] * 250,
    })
    monkeypatch.setattr(discovery.store, "read", lambda *args, **kwargs: frame)
    result = discovery.discover_equity_candidates(domains=("us_equity",), min_bars=200,
                                                  min_dollar_volume=5_000_000)
    assert result["counts"]["ready_for_research"] == 1
    assert result["candidates"][0]["price_basis"] == "unadjusted"
