from libs.data import sec_fundamentals
from scripts.materialize_sec_fundamentals import _symbols_from_args


def test_sec_mapping_covers_autodiscovered_priority_symbols():
    assert sec_fundamentals.CIK_BY_SYMBOL["MRVL"] == "0001835632"
    assert sec_fundamentals.CIK_BY_SYMBOL["AMD"] == "0000002488"
    assert sec_fundamentals.CIK_BY_SYMBOL["NVDA"] == "0001045810"
    assert sec_fundamentals.CIK_BY_SYMBOL["TSLA"] == "0001318605"


def test_sec_mapping_falls_back_to_official_dynamic_directory(monkeypatch):
    monkeypatch.setattr(sec_fundamentals, "_dynamic_cik_by_symbol",
                        lambda: {"EXAMPLE": "0000000042"})
    assert sec_fundamentals.cik_for_symbol("example") == "0000000042"


def test_materializer_can_consume_frozen_discovery_manifest(tmp_path):
    manifest = tmp_path / "universe.json"
    manifest.write_text('{"candidate_symbols": ["600519", "AAPL", "BTC-USDT", "MRVL"]}')
    assert _symbols_from_args(["--symbols-file", str(manifest), "--us-only", "--limit", "2"]) == ["AAPL", "MRVL"]


def test_materializer_uses_only_ready_candidates_from_discovery_manifest(tmp_path):
    manifest = tmp_path / "discovery.json"
    manifest.write_text(
        '{"candidates": [{"symbol": "AAPL", "status": "READY_FOR_RESEARCH"}, '
        '{"symbol": "BAD", "status": "UNKNOWN"}]}'
    )
    assert _symbols_from_args(["--symbols-file", str(manifest), "--us-only"]) == ["AAPL"]


def test_materialize_prefers_sec_acceptance_timestamp(monkeypatch):
    payload = {
        "facts": {"us-gaap": {
            "RevenueFromContractWithCustomerExcludingAssessedTax": {
                "units": {"USD": [{
                    "accn": "000-test", "end": "2025-06-30", "filed": "2025-07-20",
                    "form": "10-K", "val": 100,
                }]}
            },
            "NetIncomeLoss": {"units": {"USD": [{
                "accn": "000-test", "end": "2025-06-30", "filed": "2025-07-20",
                "form": "10-K", "val": 10,
            }]}}
        }}
    }
    captured = {}
    monkeypatch.setattr(sec_fundamentals, "_payload", lambda symbol: (payload, "sha", "facts-url"))
    monkeypatch.setattr(
        sec_fundamentals, "_submission_acceptance",
        lambda symbol: {"000-test": "2025-07-20T12:34:56.000Z"},
    )
    monkeypatch.setattr(
        sec_fundamentals.store, "write",
        lambda dataset, symbol, records, **kwargs: captured.setdefault("records", records) or 1,
    )

    result = sec_fundamentals.materialize("MRVL")

    assert result["accepted_at_rows"] == 1
    assert result["strict_pit_candidate"] is True
    assert captured["records"][0]["announcement_at"] == "2025-07-20T12:34:56.000Z"
    assert captured["records"][0]["accepted_at"] == "2025-07-20T12:34:56.000Z"
    assert captured["records"][0]["quality_flags"]["accepted_at"] == "2025-07-20T12:34:56.000Z"


def test_materialize_keeps_missing_acceptance_timestamp_unknown(monkeypatch):
    payload = {
        "facts": {"us-gaap": {
            "RevenueFromContractWithCustomerExcludingAssessedTax": {
                "units": {"USD": [{
                    "accn": "000-missing", "end": "2025-06-30", "filed": "2025-07-20",
                    "form": "10-K", "val": 100,
                }]}
            },
        }}
    }
    captured = {}
    monkeypatch.setattr(sec_fundamentals, "_payload", lambda symbol: (payload, "sha", "facts-url"))
    monkeypatch.setattr(sec_fundamentals, "_submission_acceptance", lambda symbol: {})
    monkeypatch.setattr(
        sec_fundamentals.store, "write",
        lambda dataset, symbol, records, **kwargs: captured.setdefault("records", records) or 1,
    )

    result = sec_fundamentals.materialize("MRVL")

    assert result["accepted_at_rows"] == 0
    assert result["strict_pit_candidate"] is False
    assert captured["records"][0]["announcement_at"] is None
    assert captured["records"][0]["accepted_at"] is None
    assert captured["records"][0]["quality_flags"]["accepted_at"] == "missing"
