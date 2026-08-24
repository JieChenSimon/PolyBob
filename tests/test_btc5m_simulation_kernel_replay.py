import pytest

from scripts.btc5m_simulation_kernel_replay import replay


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
