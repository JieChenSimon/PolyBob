from datetime import datetime

from libs.schemas import (
    ExecutionVenue,
    FillEvent,
    InstrumentRef,
    OrderBasket,
    OrderLeg,
    SpreadPairSnapshot,
    TradeIntent,
    TradeIntentLeg,
)


def test_trade_intent_schema_supports_multiple_legs():
    intent = TradeIntent(
        intent_id="intent-1",
        strategy_id="spread_arbitrage_v1",
        created_at=datetime.utcnow(),
        rationale="cross exchange spread",
        expected_edge_bps=85.0,
        confidence=0.82,
        legs=[
            TradeIntentLeg(
                leg_id="leg-a",
                instrument=InstrumentRef(venue=ExecutionVenue.BINANCE, symbol="BTCUSDT"),
                side="buy",
                quantity=1.0,
            ),
            TradeIntentLeg(
                leg_id="leg-b",
                instrument=InstrumentRef(venue=ExecutionVenue.HYPERLIQUID, symbol="BTC"),
                side="sell",
                quantity=1.0,
            ),
        ],
    )

    assert len(intent.legs) == 2
    assert intent.legs[0].instrument.venue == ExecutionVenue.BINANCE


def test_basket_and_fill_event_schemas_are_constructible():
    basket = OrderBasket(
        basket_id="basket-1",
        parent_intent_id="intent-1",
        created_at=datetime.utcnow(),
        status="submitting",
        legs=[
            OrderLeg(
                leg_id="leg-a",
                venue=ExecutionVenue.BINANCE,
                symbol="BTCUSDT",
                side="buy",
                quantity=1.0,
            )
        ],
    )
    fill = FillEvent(
        fill_id="fill-1",
        basket_id="basket-1",
        leg_id="leg-a",
        venue=ExecutionVenue.BINANCE,
        symbol="BTCUSDT",
        side="buy",
        price=65000.0,
        quantity=1.0,
        filled_at=datetime.utcnow(),
    )
    snapshot = SpreadPairSnapshot(
        snapshot_id="snap-1",
        pair_id="BTC-BINANCE-HL",
        timestamp=datetime.utcnow(),
        left=InstrumentRef(venue=ExecutionVenue.BINANCE, symbol="BTCUSDT"),
        right=InstrumentRef(venue=ExecutionVenue.HYPERLIQUID, symbol="BTC"),
        left_bid=64990.0,
        left_ask=65010.0,
        right_bid=65260.0,
        right_ask=65280.0,
        left_mid=65000.0,
        right_mid=65270.0,
        spread_bps=42.0,
    )

    assert basket.legs[0].venue == ExecutionVenue.BINANCE
    assert fill.basket_id == "basket-1"
    assert snapshot.spread_bps == 42.0
