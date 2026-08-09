"""Regression: SignalFusion.generate_signal must return a valid Side.

Before the fix, generate_signal used ``Side.BUY``/``Side.SELL`` which do not
exist on the enum (only BUY_YES/BUY_NO/SELL_YES/SELL_NO), so it raised
AttributeError on *every* directional signal — crashing the live strategy-engine
path (modules/strategy_engine/service.py) and hybrid_strategy. This guards the
mapping direction>0 -> BUY_YES, direction<0 -> SELL_YES.
"""

from __future__ import annotations

import asyncio

from libs.schemas import Side
from strategies.signal_fusion import SignalFusion


def _generate(features):
    return asyncio.run(SignalFusion().generate_signal(features))


def test_bullish_direction_maps_to_buy_yes():
    signal = _generate({"market_id": "m1", "ai_direction": 1, "ai_confidence": 0.9})
    assert signal is not None
    assert signal.side is Side.BUY_YES


def test_bearish_direction_maps_to_sell_yes():
    signal = _generate({"market_id": "m1", "ai_direction": -1, "ai_confidence": 0.9})
    assert signal is not None
    assert signal.side is Side.SELL_YES


def test_generate_signal_never_raises_attributeerror_on_direction():
    # The whole point of the regression: a directional signal must not blow up.
    for direction in (1, -1):
        signal = _generate({"market_id": "m1", "ai_direction": direction, "ai_confidence": 0.8})
        assert signal.side in {Side.BUY_YES, Side.SELL_YES}


def test_no_signal_when_flat():
    assert _generate({"market_id": "m1"}) is None
