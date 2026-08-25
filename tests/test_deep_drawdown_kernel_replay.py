from scripts.deep_drawdown_kernel_replay import _fundamental_gate_status


def test_fundamental_gate_status_distinguishes_event_approval_from_unknown():
    events = [{"event_date": "2025-09-19T00:00:00+00:00"}]
    assert _fundamental_gate_status(events, None) == "UNKNOWN_NO_TRADE"
    assert _fundamental_gate_status(events, {"2025-09-19"}) == "PASS_EVENT_DATE_GATE"
    assert _fundamental_gate_status(events, {"2025-09-20"}) == "UNKNOWN_NO_TRADE"
