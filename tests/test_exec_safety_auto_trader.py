"""P3: auto-trader state survives restart, and the signal is not mislabeled AI."""
from services.auto_trader.engine import TradingEngine
from services.auto_trader.state_store import AutoTraderStateStore


def test_state_recovers_after_restart(tmp_path):
    db_path = tmp_path / "auto_trader.db"
    store = AutoTraderStateStore(db_path)

    engine = TradingEngine(10_000.0, engine_id="test_demo", state_store=store)
    # Simulate a completed trade cycle mutating the book.
    engine.execute_trade({"direction": "long", "confidence": 0.4}, 100.0)
    engine.execute_trade({"direction": "short", "confidence": 0.4}, 110.0)

    capital_before = engine.capital
    trades_before = len(engine.trades)
    assert trades_before == 2  # open_long + close_long
    assert capital_before != 10_000.0  # book actually moved

    # "Restart": a fresh engine bound to the same store must recover the book,
    # not silently reset PnL to the initial capital.
    recovered = TradingEngine(10_000.0, engine_id="test_demo", state_store=store)
    assert recovered.capital == capital_before
    assert recovered.position == engine.position
    assert len(recovered.trades) == trades_before


def test_signal_is_labeled_heuristic_not_ai():
    engine = TradingEngine(10_000.0, persist=False)
    # The method is named honestly (no ai_signal) ...
    assert not hasattr(engine, "ai_signal")
    assert hasattr(engine, "heuristic_signal")
    # ... and self-reports as a heuristic, not an AI/model output.
    signal = engine.heuristic_signal({"rsi": 40})
    assert signal["source"] == "heuristic"
    assert engine.SIGNAL_SOURCE == "heuristic"


def test_persist_false_does_not_touch_disk(tmp_path):
    # A non-persisting engine keeps working with no store attached.
    engine = TradingEngine(10_000.0, persist=False)
    assert engine.state_store is None
    engine.execute_trade({"direction": "long", "confidence": 0.4}, 100.0)
    assert engine.position > 0
