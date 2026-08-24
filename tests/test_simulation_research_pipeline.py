from scripts.simulation_research_pipeline import _select_candidate


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
