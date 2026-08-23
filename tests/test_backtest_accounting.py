from datetime import datetime

import pytest

from libs.backtest import BacktestConfig, BacktestEngine, simulate_position_series
from libs.schemas import Side


def test_missing_mark_is_unknown_and_update_fails_closed():
    engine = BacktestEngine()
    assert engine.execute_signal(datetime.utcnow(), "BTC", Side.BUY_YES, 100.0, 0.01)
    assert engine.mark_to_market({}) == ("unknown_missing_price", None)
    with pytest.raises(ValueError, match="cannot mark portfolio"):
        engine.update_equity(datetime.utcnow(), {})


def test_short_requires_margin_and_can_be_closed():
    engine = BacktestEngine(BacktestConfig(initial_capital=110.0, allow_short=True))
    now = datetime.utcnow()
    assert engine.execute_signal(now, "BTC", Side.SELL_YES, 100.0, 1.0)
    assert engine.positions["BTC"] == -1.0
    assert engine.execute_signal(now, "BTC", Side.BUY_YES, 90.0, 1.0)
    assert engine.positions["BTC"] == 0.0

    constrained = BacktestEngine(BacktestConfig(initial_capital=10.0, allow_short=True))
    assert not constrained.execute_signal(now, "BTC", Side.SELL_YES, 100.0, 1.0)


def test_position_series_is_causal_and_costed():
    returns, result = simulate_position_series(
        [100.0, 110.0, 110.0], [1.0, 1.0, 0.0], cost_bps=10.0
    )
    # Entry at bar 0 earns the bar-0 -> bar-1 move; exit at bar 2 cannot use
    # the future bar-2 close to manufacture a return.
    assert returns[0] > 0.09
    assert result["total_fees"] > 0
