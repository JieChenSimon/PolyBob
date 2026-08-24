from scripts.backfill_daily_price_basis import _declared_basis, _missing


def test_price_basis_backfill_handles_parquet_nan_and_known_providers():
    assert _missing(float("nan"))
    assert _missing(None)
    assert _declared_basis("tencent_migrated") == "forward_adjusted"
    assert _declared_basis("okx") == "unadjusted"
    assert _declared_basis("untrusted_provider") is None
