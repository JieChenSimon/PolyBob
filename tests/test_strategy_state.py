"""Persistence tests for adaptive strategy state (signal fusion weights)."""
import json

from libs.db import fact_store
from libs.db.strategy_state import StrategyStateStore
from strategies.signal_fusion import SignalFusion


def test_state_store_round_trip(tmp_path):
    store = StrategyStateStore(tmp_path / "state.sqlite3")
    store.save_state("demo", {"weights": {"a": 0.7}, "performance_history": {"a": [1.0]}})

    loaded = store.load_state("demo")
    assert loaded == {"weights": {"a": 0.7}, "performance_history": {"a": [1.0]}}

    # Upsert replaces prior state.
    store.save_state("demo", {"weights": {"a": 0.2}, "performance_history": {"a": []}})
    assert store.load_state("demo")["weights"] == {"a": 0.2}


def test_state_store_missing_returns_empty(tmp_path):
    store = StrategyStateStore(tmp_path / "state.sqlite3")
    assert store.load_state("never_saved") == {}


def test_signal_fusion_weights_survive_reinstantiation(tmp_path):
    db_path = tmp_path / "state.sqlite3"
    store = StrategyStateStore(db_path)

    first = SignalFusion(state_store=store)
    default_weights = dict(first.weights)
    # Reward one signal repeatedly so weights shift away from uniform.
    for _ in range(10):
        first.update_performance("dual_ma", 1.0)
        first.update_performance("rsi", -1.0)
    assert first.weights != default_weights

    # A fresh instance with the same store restores the learned state.
    second = SignalFusion(state_store=StrategyStateStore(db_path))
    assert second.weights == first.weights
    assert second.performance_history == first.performance_history

    # Without a store, behavior is unchanged (defaults, no persistence).
    third = SignalFusion()
    assert third.weights == default_weights


def test_signal_fusion_corrupt_state_degrades_to_defaults(tmp_path):
    db_path = tmp_path / "state.sqlite3"
    store = StrategyStateStore(db_path)
    store.save_state("signal_fusion", {"weights": {"a": 1.0}})  # write something first

    # Corrupt the raw row: invalid JSON.
    with fact_store.connect(db_path) as connection:
        connection.execute(
            "UPDATE strategy_state SET state_json = ? WHERE strategy_id = ?",
            ("{not json", "signal_fusion"),
        )

    fusion = SignalFusion(state_store=StrategyStateStore(db_path))
    assert fusion.weights == {
        "dual_ma": 0.20,
        "rsi": 0.20,
        "macd": 0.20,
        "bollinger": 0.20,
        "ai_predict": 0.20,
    }


def test_signal_fusion_rejects_state_with_unknown_signal_names(tmp_path):
    db_path = tmp_path / "state.sqlite3"
    store = StrategyStateStore(db_path)
    store.save_state(
        "signal_fusion",
        {
            "weights": {"rogue_signal": 1.0},
            "performance_history": {"rogue_signal": [1.0]},
        },
    )

    fusion = SignalFusion(state_store=StrategyStateStore(db_path))
    assert set(fusion.weights) == {"dual_ma", "rsi", "macd", "bollinger", "ai_predict"}
    assert fusion.weights["dual_ma"] == 0.20


def test_state_store_table_shape(tmp_path):
    db_path = tmp_path / "state.sqlite3"
    StrategyStateStore(db_path).save_state("demo", {"k": "v"})
    with fact_store.connect(db_path) as connection:
        row = connection.execute(
            "SELECT strategy_id, state_json, updated_at FROM strategy_state"
        ).fetchone()
    assert row["strategy_id"] == "demo"
    assert json.loads(row["state_json"]) == {"k": "v"}
    assert row["updated_at"]
