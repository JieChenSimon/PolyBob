from libs.data import run_manifest


def test_manifest_exposes_stable_input_and_model_lineage(tmp_path):
    manifest = run_manifest.pin(
        "forecast",
        params={"model_revision": "kronos-v1", "horizon": 5},
    )
    manifest.record_input("daily_bars", batch_id="part-abc", rows=100)
    first = manifest.input_hash
    assert manifest.model_hash
    assert manifest.has_lineage
    manifest.save(tmp_path / "result.json")
    saved = (tmp_path / "result.manifest.json").read_text()
    assert first in saved
    assert "has_lineage" in saved
