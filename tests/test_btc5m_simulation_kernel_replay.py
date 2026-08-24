import pytest

from scripts.btc5m_simulation_kernel_replay import replay
from scripts.btc5m_mispricing import _period_audit, _should_skip_checkpoint_window, _time_split_audit


@pytest.mark.asyncio
async def test_known_answer_event_is_filled_and_settled(tmp_path):
    row = {
        "window_start": 1_700_000_000,
        "window_end": 1_700_000_300,
        "decision_ts": 1_700_000_120,
        "model_probability": 0.70,
        "market_probability": 0.50,
        "outcome_up": 1,
        "gamma_raw_sha256": "gamma",
        "clob_raw_sha256": "clob",
        "okx_raw_sha256": "okx",
    }

    result = await replay([row], 1.0, tmp_path)

    assert result["candidate_events"] == 1
    assert result["fills"] == 2
    assert result["open_positions"] == 0
    assert result["risk_rejections"] == 0
    assert result["risk_rejection_reasons"] == {}
    assert result["risk_rejections_by_stage"] == {}
    assert result["unresolved_positions"] == []
    assert result["metrics"]["closed_trade_count"] == 1
    assert result["metrics"]["equity_curve_degraded"] is False


def test_checkpoint_open_state_is_retryable():
    assert _should_skip_checkpoint_window("sample") is True
    assert _should_skip_checkpoint_window("no_market") is True
    assert _should_skip_checkpoint_window("open") is False
    assert _should_skip_checkpoint_window("retry:no_quote") is False


def test_period_audit_is_explicit_and_not_annualized_from_event_mean():
    audit = _period_audit([
        {"date": "2026-01-02", "entry_price": 0.5, "pnl": 0.48},
        {"date": "2026-01-02", "entry_price": 0.5, "pnl": -0.52},
    ])
    assert audit["basis"] == "fixed_initial_capital_per_event"
    assert audit["monthly"][0]["month"] == "2026-01"
    assert audit["return_target"]["status"] == "UNKNOWN"
    assert audit["max_drawdown"] >= 0


def test_time_split_is_fixed_and_fail_closed_until_oos_has_independent_days():
    rows = [{"date": "2026-08-19", "entry_price": 0.5, "pnl": 0.1}]
    rows += [{"date": "2026-08-20", "entry_price": 0.5, "pnl": 0.1}]
    split = _time_split_audit(rows, oos_start="2026-08-20")
    assert split["oos_start"] == "2026-08-20"
    assert split["status"] == "UNKNOWN"
    assert split["oos"]["independent_days"] == 1
