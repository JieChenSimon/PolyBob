from libs.quant.tsmom_audit import audit_candidate


def _fold(**changes):
    base = {
        "median_oos_return": 0.02,
        "positive_oos_fraction": 0.6,
        "median_oos_closed_trades": 8.0,
        "median_full_max_drawdown": 0.2,
    }
    return {**base, **changes}


def test_negative_oos_is_rejected():
    result = audit_candidate([_fold(median_oos_return=-0.01)] * 4)
    assert not result["approved_for_next_stage"]
    assert "nonpositive_median_oos_return" in result["reasons"]


def test_zero_trade_low_drawdown_is_rejected():
    result = audit_candidate([_fold(median_oos_closed_trades=0, median_full_max_drawdown=0)] * 4)
    assert not result["approved_for_next_stage"]
    assert "median_oos_closed_trades<5" in result["reasons"]


def test_unstable_candidate_is_rejected():
    result = audit_candidate([_fold(), _fold(), _fold(median_oos_return=0), _fold()])
    assert not result["approved_for_next_stage"]


def test_stable_screen_candidate_can_reach_next_gate():
    result = audit_candidate([_fold()] * 4)
    assert result["approved_for_next_stage"]
