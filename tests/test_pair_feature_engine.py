import asyncio

from libs.schemas import ExecutionVenue, InstrumentRef
from services.pair_feature_engine import PairDefinition, PairFeatureEngineService


def test_pair_feature_engine_builds_snapshot():
    async def fetch_quotes():
        return {
            "left": {"bid": 65010.0, "ask": 65020.0},
            "right": {"bid": 64980.0, "ask": 64990.0},
        }

    service = PairFeatureEngineService(
        pair_definitions=[
            PairDefinition(
                pair_id="btc_test_pair",
                left=InstrumentRef(venue=ExecutionVenue.BINANCE, symbol="BTCUSDT"),
                right=InstrumentRef(venue=ExecutionVenue.HYPERLIQUID, symbol="BTC"),
                fetch_quotes=fetch_quotes,
            )
        ]
    )

    snapshot = asyncio.run(service._build_snapshot(service.pair_definitions[0]))

    assert snapshot is not None
    assert snapshot.pair_id == "btc_test_pair"
    assert snapshot.net_edge_bps is not None
    assert snapshot.opportunity_side in {"long_right_short_left", "long_left_short_right"}
