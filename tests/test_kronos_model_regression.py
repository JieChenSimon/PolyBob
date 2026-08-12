"""Pinned heavyweight regression for the ignored local Kronos model cache."""

from __future__ import annotations

import datetime as dt
import importlib.util
import math
from pathlib import Path

import numpy as np
import pytest

from libs.forecasting.contracts import AssetClass, BarInterval, CanonicalBar, CanonicalBarFrame
from libs.forecasting.kronos import KronosLab, KronosLabConfig

pytestmark = pytest.mark.forecasting_model


def test_kronos_base_pinned_cpu_regression():
    root = Path("data/models/kronos")
    if importlib.util.find_spec("huggingface_hub") is None or not (root / "Kronos-base/model.safetensors").is_file():
        pytest.skip("run uv sync --extra forecasting and scripts/kronos_models.py pull")
    lab = KronosLab(
        KronosLabConfig(
            enabled=True,
            root=root,
            device="cpu",
            paths=1,
            temperature=1.0,
            top_k=1,
            top_p=1.0,
        )
    )
    assert lab.readiness(verify_hashes=True)["ready"] is True
    bars = []
    for index in range(40):
        close = 100 + index * 0.15 + math.sin(index / 3) * 0.4
        open_ = close - 0.1
        volume = 1000 + index * 10
        bars.append(
            CanonicalBar(
                timestamp=dt.datetime(2025, 1, 1, tzinfo=dt.UTC) + dt.timedelta(days=index),
                open=open_,
                high=close + 0.3,
                low=open_ - 0.25,
                close=close,
                volume=volume,
                amount=volume * close,
            )
        )
    frame = CanonicalBarFrame(
        instrument_id="SYNTH-REGRESSION",
        asset_class=AssetClass.CRYPTO_SPOT,
        venue="TEST",
        interval=BarInterval.ONE_DAY,
        source="generated-fixture",
        fetched_at=dt.datetime(2025, 2, 10, tzinfo=dt.UTC),
        bars=tuple(bars),
    )
    artifact = lab.forecast(frame, horizon=2)
    obtained = np.array([point.close_p50 for point in artifact.points])
    np.testing.assert_allclose(obtained, [106.10016632080078, 106.40398406982422], rtol=1e-5)
