from datetime import datetime, timedelta

import pytest

from libs.backtest import BacktestEngine
from libs.schemas import Side


def test_signal_cannot_fill_before_effective_time():
    engine = BacktestEngine()
    effective = datetime(2026, 1, 1, 0, 0, 1)
    with pytest.raises(ValueError, match="effective_at"):
        engine.execute_signal(
            effective - timedelta(microseconds=1), "BTC", Side.BUY_YES,
            100.0, 0.01, effective_at=effective,
        )
