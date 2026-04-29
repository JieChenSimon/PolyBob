import asyncio

from strategies.spread_arbitrage_v1 import SpreadArbitrageV1


class FakeIntentService:
    def __init__(self):
        self.created = []
        self.submitted = []

    async def create_intent(self, **kwargs):
        intent_id = f"intent_{len(self.created) + 1}"
        payload = {"intent_id": intent_id, **kwargs}
        self.created.append(payload)
        return {"intent_id": intent_id}

    async def submit_intent(self, intent_id: str):
        self.submitted.append(intent_id)
        return {"intent_id": intent_id}


def test_spread_arbitrage_strategy_generates_intent_on_pair_snapshot():
    service = FakeIntentService()
    strategy = SpreadArbitrageV1(
        {
            "min_net_edge_bps": 10.0,
            "min_abs_spread_bps": 5.0,
            "min_confidence": 0.4,
            "order_quantity": 0.01,
            "cooldown_seconds": 0,
        },
        intent_service=service,
    )

    asyncio.run(strategy.start())
    asyncio.run(
        strategy._on_pair_snapshot(
            {
                "pair_id": "btc_binance_hyperliquid",
                "left": {"venue": "binance", "symbol": "BTCUSDT"},
                "right": {"venue": "hyperliquid", "symbol": "BTC"},
                "left_bid": 65010.0,
                "left_ask": 65020.0,
                "right_bid": 64970.0,
                "right_ask": 64980.0,
                "spread_bps": 6.0,
                "z_score": 1.5,
                "net_edge_bps": 12.0,
                "opportunity_side": "long_right_short_left",
            }
        )
    )

    assert len(service.created) == 1
    assert len(service.submitted) == 1
    asyncio.run(strategy.stop())
