from datetime import datetime, timedelta

from libs.backtest.walk_forward import WalkForwardAnalyzer


def test_purge_and_embargo_create_real_gap():
    start = datetime(2026, 1, 1)
    windows = WalkForwardAnalyzer(
        train_months=1, test_months=1, step_months=1,
        purge_days=3, embargo_days=5,
    ).generate_windows(start, start + timedelta(days=75))
    assert windows
    window = windows[0]
    raw_train_end = start + timedelta(days=30)
    assert window.train_end == raw_train_end - timedelta(days=3)
    assert window.test_start == raw_train_end + timedelta(days=5)
    assert window.test_start > window.train_end
