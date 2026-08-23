from __future__ import annotations

import datetime as dt

import pytest

from libs.forecasting.contracts import (
    AssetClass,
    BarInterval,
    CanonicalBar,
    CanonicalBarFrame,
    ForecastArtifact,
    ForecastPoint,
    ForecastStatus,
)


def bar(day: int, *, low: float = 9.0, high: float = 12.0) -> CanonicalBar:
    return CanonicalBar(
        timestamp=dt.datetime(2026, 1, 1, tzinfo=dt.UTC) + dt.timedelta(days=day - 1),
        open=10.0,
        high=high,
        low=low,
        close=11.0,
        volume=100.0,
    )


def test_frame_preserves_explicit_amount_derivation_state():
    frame = CanonicalBarFrame(
        instrument_id="BTC-USDT",
        asset_class=AssetClass.CRYPTO_SPOT,
        venue="OKX",
        interval=BarInterval.ONE_DAY,
        source="okx",
        fetched_at=dt.datetime.now(dt.UTC),
        bars=tuple(bar(index) for index in range(1, 33)),
    )
    frame.validate()
    assert frame.feature_mode == "ohlcv_amount_derived"


def test_invalid_ohlc_is_rejected():
    with pytest.raises(ValueError, match="low <="):
        bar(1, low=10.5).validate()


def test_short_context_is_rejected():
    frame = CanonicalBarFrame(
        instrument_id="AAPL",
        asset_class=AssetClass.US_EQUITY,
        venue="US",
        interval=BarInterval.ONE_DAY,
        source="test",
        fetched_at=dt.datetime.now(dt.UTC),
        bars=(bar(1),),
    )
    with pytest.raises(ValueError, match="at least 32"):
        frame.validate()


def test_forecast_artifact_exposes_complete_lineage():
    artifact = ForecastArtifact(
        run_id="run-1",
        status=ForecastStatus.READY,
        instrument_id="AAPL",
        asset_class=AssetClass.US_EQUITY,
        interval=BarInterval.ONE_DAY,
        as_of=dt.datetime(2026, 1, 31, tzinfo=dt.UTC),
        source="provider",
        model_id="model",
        model_revision="model-rev",
        tokenizer_id="tokenizer",
        tokenizer_revision="tokenizer-rev",
        context_rows=64,
        horizon=5,
        feature_mode="ohlcv_amount_derived",
        calendar_quality="verified",
        paths=3,
        last_close=100.0,
        expected_return=0.02,
        up_probability=0.6,
        points=(ForecastPoint(
            timestamp=dt.datetime(2026, 2, 5, tzinfo=dt.UTC),
            open_p50=101.0, high_p50=103.0, low_p50=99.0,
            close_p10=98.0, close_p50=102.0, close_p90=106.0,
        ),),
        input_hash="input-hash",
    )
    payload = artifact.to_dict()
    assert payload["lineage"]["run_id"] == "run-1"
    assert payload["lineage"]["input_hash"] == "input-hash"
    assert payload["lineage"]["model_hash"]
    assert payload["lineage"]["data_batch"]["context_rows"] == 64
    assert payload["lineage"]["parameters"]["horizon"] == 5
