from scripts.audit_btc5m_report_lineage import build_manifest


def test_lineage_manifest_is_fail_closed_for_non_tradable_report(tmp_path):
    report = tmp_path / "report.json"
    report.write_text('{"generated_at":"2026-08-25","real_data_only":true,"tradable_evidence":false}')
    manifest = build_manifest("event", report)
    assert manifest["pit_status"] == "UNKNOWN"
    assert manifest["tradable_evidence"] is False
    assert manifest["degradation"]["status"] == "diagnostic_only"
    assert len(manifest["report_sha256"]) == 64
