from scripts.simulation_research_pipeline import (
    _diagnostic_candidate,
    _oos_evidence,
    _select_candidate,
    _verdict,
    ProgressReporter,
)
from datetime import UTC, datetime
from pytest import approx


def test_candidate_selection_never_uses_oos_score():
    candidates = [
        {
            "candidate": {"id": "train_winner"},
            "score_train_mean_return": 0.02,
            "score_train_median_return": 0.01,
            "score_oos_mean_return": -0.10,
        },
        {
            "candidate": {"id": "oos_winner"},
            "score_train_mean_return": -0.01,
            "score_train_median_return": -0.01,
            "score_oos_mean_return": 0.20,
        },
    ]

    selected = _select_candidate(candidates)

    assert selected is not None
    assert selected["candidate"]["id"] == "train_winner"


def test_candidate_selection_blocks_missing_training_evidence():
    assert _select_candidate([{"score_train_mean_return": 0.2,
                               "score_train_median_return": None,
                               "score_oos_mean_return": 1.0}]) is None


def test_candidate_selection_blocks_positive_mean_with_negative_median():
    assert _select_candidate([{"score_train_mean_return": 0.5,
                               "score_train_median_return": -0.01,
                               "score_oos_mean_return": 1.0}]) is None


def test_diagnostic_candidate_preserves_domain_coverage_without_promotion():
    candidate = _diagnostic_candidate([
        {"candidate": {"id": "least_bad"}, "score_train_median_return": -0.01,
         "score_train_mean_return": -0.02},
        {"candidate": {"id": "worse"}, "score_train_median_return": -0.03,
         "score_train_mean_return": -0.01},
    ])
    assert candidate["candidate"]["id"] == "least_bad"


def test_oos_evidence_reports_return_drawdown_and_quarter_stability():
    split = datetime(2024, 1, 1, tzinfo=UTC)
    evidence = _oos_evidence([
        {"ts": "2023-12-29T00:00:00+00:00", "return": 0.50},
        {"ts": "2024-01-02T00:00:00+00:00", "return": 0.10},
        {"ts": "2024-02-01T00:00:00+00:00", "return": -0.05},
        {"ts": "2024-04-01T00:00:00+00:00", "return": 0.20},
    ], split)
    assert evidence["status"] == "ANALYZED"
    assert evidence["return"] == approx(0.254)
    assert evidence["max_drawdown"] > 0
    assert evidence["stability_rate"] == 1.0


def test_verdict_blocks_unknown_research_evidence():
    result = {"status": "ANALYZED", "metrics": {
        "equity_curve_degraded": False, "closed_trade_count": 20,
        "total_return": 0.1, "max_drawdown": 0.1,
    }, "research_evidence": {"oos": {}, "multiple_testing": {"status": "BLOCKED"}}}
    verdict, reasons = _verdict(result)
    assert verdict == "FAIL"
    assert "oos_return_unknown" in reasons
    assert "multiple_testing_unknown" in reasons


def test_verdict_blocks_negative_oos_and_overfit_pbo():
    result = {"status": "ANALYZED", "metrics": {
        "equity_curve_degraded": False, "closed_trade_count": 20,
        "total_return": 0.1, "max_drawdown": 0.1,
    }, "research_evidence": {
        "oos": {"return": -0.01, "stability_rate": 0.25},
        "multiple_testing": {"status": "ANALYZED", "pbo": 0.5714},
    }}
    verdict, reasons = _verdict(result)
    assert verdict == "FAIL"
    assert "non_positive_oos_return" in reasons
    assert "oos_stability<50%" in reasons
    assert "pbo>25%" in reasons


def test_progress_reporter_persists_fraction_and_eta(tmp_path):
    path = tmp_path / "progress.json"
    reporter = ProgressReporter(path, total=2)
    reporter.complete_one("AAPL")
    payload = __import__("json").loads(path.read_text())
    assert payload["status"] == "running"
    assert payload["completed_runs"] == 1
    assert payload["total_runs"] == 2
    assert payload["fraction"] == approx(0.5)
    assert payload["current"] == "AAPL"
