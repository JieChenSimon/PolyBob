import datetime as dt
from types import SimpleNamespace

from libs.forecasting.contracts import ForecastStatus
from modules.simulation.sources import KronosForecastLabSource


def artifact(expected_return: float):
    return SimpleNamespace(
        status=ForecastStatus.READY,
        expected_return=expected_return,
        up_probability=0.75,
        last_close=100.0,
        instrument_id="AAPL",
        as_of=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        run_id="run-1",
        model_revision="revision",
    )


def test_forecast_source_emits_lab_only_simulation_signal():
    signal = KronosForecastLabSource(minimum_abs_return=0.01).signals_for_artifact(artifact(0.02))[0]
    assert signal.side == "buy"
    assert signal.signal_meta["promotion_status"] == "lab_only"
    assert signal.signal_meta["trade_permission"] is False


def test_forecast_source_suppresses_small_moves():
    assert KronosForecastLabSource(minimum_abs_return=0.01).signals_for_artifact(artifact(0.001)) == []
