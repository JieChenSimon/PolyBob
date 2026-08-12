import pytest

from libs.forecasting.evaluation import TerminalForecastObservation, evaluate_terminal_forecasts


def test_evaluation_compares_against_last_close_and_counts_clusters():
    result = evaluate_terminal_forecasts([
        TerminalForecastObservation("2026-W01", 100, 104, 101, 103, 105),
        TerminalForecastObservation("2026-W02", 100, 96, 95, 97, 99),
    ])
    assert result.n_clusters == 2
    assert result.direction_accuracy == 1.0
    assert result.interval_80_coverage == 1.0
    assert result.beats_naive is True
    assert result.promotion_status == "lab_only"


def test_evaluation_rejects_malformed_interval():
    with pytest.raises(ValueError, match="p10"):
        evaluate_terminal_forecasts([
            TerminalForecastObservation("one", 100, 101, 103, 102, 101),
        ])
