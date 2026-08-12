from pathlib import Path

import pytest

from libs.forecasting.kronos import ForecastUnavailable, KronosLab, KronosLabConfig


def test_forecasting_is_disabled_by_default():
    lab = KronosLab(KronosLabConfig(root=Path("does-not-exist")))
    with pytest.raises(ForecastUnavailable, match="disabled"):
        lab.forecast(None)  # type: ignore[arg-type]


def test_readiness_reports_missing_artifacts_as_not_ready(tmp_path):
    state = KronosLab(KronosLabConfig(root=tmp_path)).readiness()
    assert state["ready"] is False
    assert state["enabled"] is False
    assert state["promotion_status"] == "lab_only"
    assert "missing" in state["reason"]
