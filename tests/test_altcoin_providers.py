import json
import os
from pathlib import Path

import httpx
import pytest

from libs.crypto.discovery.providers.binance_alpha import BinanceAlphaProvider
from libs.crypto.discovery.providers.binance_futures import BinanceFuturesProvider
from libs.crypto.discovery.providers.dex_screener import DexScreenerProvider
from libs.crypto.discovery.providers.evm import EvmEvidenceProvider
from libs.crypto.discovery.providers.http import build_provider_http_client, request_json
from libs.crypto.discovery.providers.solana import SolanaEvidenceProvider


FIXTURES = Path(__file__).parent / "fixtures" / "altcoin_discovery"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.mark.asyncio
async def test_alpha_provider_parses_real_contract_identity():
    payload = load_fixture("binance_alpha_bsc.json")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))

    async with httpx.AsyncClient(transport=transport) as client:
        tokens = await BinanceAlphaProvider(client).list_alpha_tokens("56")

    assert tokens[0].asset_id == "56:0x8b194370825e37b33373e74a41009161808c1488"
    assert tokens[0].symbol == "VELVET"
    assert tokens[0].holders_top10_percent == pytest.approx(89.51263228445335)
    assert tokens[0].is_alpha is True
    assert tokens[0].observed_at.tzinfo is not None


@pytest.mark.asyncio
async def test_alpha_provider_reads_all_pages():
    base = load_fixture("binance_alpha_bsc.json")
    requested_pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requested_pages.append(body["page"])
        payload = json.loads(json.dumps(base))
        payload["data"]["total"] = 2
        payload["data"]["size"] = 1
        payload["data"]["page"] = body["page"]
        payload["data"]["tokens"][0]["contractAddress"] = f"0x{body['page']}"
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        tokens = await BinanceAlphaProvider(client).list_alpha_tokens("56", page_size=1)

    assert requested_pages == [1, 2]
    assert [token.contract_address for token in tokens] == ["0x1", "0x2"]


@pytest.mark.asyncio
async def test_futures_provider_keeps_only_live_usdt_perpetuals():
    payload = load_fixture("binance_futures_exchange_info.json")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))

    async with httpx.AsyncClient(transport=transport) as client:
        symbols = await BinanceFuturesProvider(client).list_perpetuals()

    assert [item.symbol for item in symbols] == ["VELVETUSDT"]
    assert symbols[0].quantity_step == 1.0


@pytest.mark.asyncio
async def test_futures_provider_falls_back_to_official_ws_tickers_on_rest_451():
    websocket_calls = 0

    async def websocket_request(method: str, params: dict) -> list[dict]:
        nonlocal websocket_calls
        websocket_calls += 1
        assert method == "ticker.price"
        assert params == {}
        return [
            {"symbol": "VELVETUSDT", "price": "0.50", "time": 1782628322872},
            {"symbol": "BTCUSDT_260925", "price": "60000", "time": 1782628322872},
            {"symbol": "ETHUSDC", "price": "1600", "time": 1782628322872},
        ]

    transport = httpx.MockTransport(
        lambda request: httpx.Response(451, json={"code": 0, "msg": "restricted location"})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        provider = BinanceFuturesProvider(
            client,
            websocket_request=websocket_request,
        )
        symbols = await provider.list_perpetuals()
        signals = await provider.market_signals("VELVETUSDT")

    assert [item.symbol for item in symbols] == ["VELVETUSDT"]
    assert symbols[0].base_asset == "VELVET"
    assert symbols[0].contract_type == "PERPETUAL"
    assert signals.price == 0.50
    assert signals.funding_rate is None
    assert websocket_calls == 1


@pytest.mark.asyncio
async def test_alpha_provider_maps_alpha_id_and_loads_official_klines():
    rank_payload = load_fixture("binance_alpha_bsc.json")
    contract = rank_payload["data"]["tokens"][0]["contractAddress"]
    token_list_payload = {
        "code": "000000",
        "data": [
            {
                "alphaId": "ALPHA_267",
                "chainId": "56",
                "contractAddress": contract,
                "symbol": "VELVET",
            }
        ],
    }
    kline_payload = {
        "code": "000000",
        "data": [
            [
                "1782259200000",
                "0.45976071",
                "0.49315117",
                "0.38290684",
                "0.48051639",
                "970211.86",
                "1782345599999",
                "446064.56",
                "4786",
            ]
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/alpha/all/token/list"):
            return httpx.Response(200, json=token_list_payload)
        if request.url.path.endswith("/alpha-trade/klines"):
            assert request.url.params["symbol"] == "ALPHA_267USDT"
            return httpx.Response(200, json=kline_payload)
        return httpx.Response(200, json=rank_payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = BinanceAlphaProvider(client)
        token = (await provider.list_alpha_tokens("56"))[0]
        candles = await provider.klines(token, interval="1d", limit=180)

    assert token.alpha_id == "ALPHA_267"
    assert candles[0].close == pytest.approx(0.48051639)
    assert candles[0].volume == pytest.approx(970211.86)


@pytest.mark.asyncio
async def test_futures_provider_parses_daily_klines():
    payload = [
        [1782518400000, "1.0", "1.2", "0.9", "1.1", "2500", 1782604799999, "2700", 120]
    ]
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))

    async with httpx.AsyncClient(transport=transport) as client:
        candles = await BinanceFuturesProvider(client).klines("VELVETUSDT", limit=180)

    assert candles[0].open_time_ms == 1782518400000
    assert candles[0].close == 1.1
    assert candles[0].volume == 2500.0


@pytest.mark.asyncio
async def test_futures_provider_combines_price_funding_open_interest_and_positioning():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/ticker/24hr"):
            return httpx.Response(
                200,
                json={"lastPrice": "1.45", "quoteVolume": "5000000"},
            )
        if path.endswith("/premiumIndex"):
            return httpx.Response(200, json={"lastFundingRate": "-0.001"})
        if path.endswith("/openInterestHist"):
            return httpx.Response(
                200,
                json=[
                    {"sumOpenInterestValue": "1000000"},
                    {"sumOpenInterestValue": "1200000"},
                ],
            )
        if path.endswith("/globalLongShortAccountRatio"):
            return httpx.Response(200, json=[{"longShortRatio": "0.8"}])
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        signals = await BinanceFuturesProvider(client).market_signals("VELVETUSDT")

    assert signals.price == 1.45
    assert signals.volume_24h_usd == 5_000_000.0
    assert signals.funding_rate == -0.001
    assert signals.open_interest_change == pytest.approx(0.2)
    assert signals.long_short_ratio == 0.8


@pytest.mark.asyncio
async def test_smart_money_provider_rejects_unsupported_chain_without_request():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        evidence = await BinanceAlphaProvider(client).list_smart_money("1")

    assert evidence.status == "unsupported"
    assert evidence.value is None
    assert calls == 0


@pytest.mark.asyncio
async def test_smart_money_provider_keeps_real_contract_and_inflow():
    payload = load_fixture("binance_smart_money_bsc.json")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))

    async with httpx.AsyncClient(transport=transport) as client:
        evidence = await BinanceAlphaProvider(client).list_smart_money("56")

    assert evidence.status == "observed"
    assert evidence.value[0]["ca"] == "0x92aa03137385f18539301349dcfc9ebc923ffb10"
    assert evidence.value[0]["inflow"] == pytest.approx(82.2889464775926)


@pytest.mark.asyncio
async def test_dex_screener_provider_keeps_pair_liquidity_and_source():
    payload = [
        {
            "chainId": "bsc",
            "pairAddress": "0xpair",
            "priceUsd": "1.45",
            "liquidity": {"usd": 6232200.77},
            "volume": {"h24": 6124792.81},
        }
    ]
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))

    async with httpx.AsyncClient(transport=transport) as client:
        evidence = await DexScreenerProvider(client).token_pairs(
            "bsc", "0x8b194370825e37b33373e74a41009161808c1488"
        )

    assert evidence.status == "observed"
    assert evidence.provider == "dex_screener"
    assert evidence.value[0]["liquidity"]["usd"] == pytest.approx(6232200.77)


@pytest.mark.asyncio
async def test_shared_transport_rejects_scalar_json():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json="not-an-object"))

    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ValueError, match="Expected JSON object or list"):
            await request_json(client, "GET", "https://provider.test/value")


@pytest.mark.asyncio
async def test_evm_adapter_preserves_observed_block_number():
    def handler(request: httpx.Request) -> httpx.Response:
        method = json.loads(request.content)["method"]
        result = (
            "0x1234"
            if method == "eth_blockNumber"
            else "0x0000000000000000000000000000000000000000000000000de0b6b3a7640000"
        )
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        evidence = await EvmEvidenceProvider(client, rpc_urls={"56": "https://rpc.test"}).token_supply(
            chain_id="56",
            contract_address="0x8b194370825e37b33373e74a41009161808c1488",
            decimals=18,
        )

    assert evidence.status == "observed"
    assert evidence.block_number == 0x1234
    assert evidence.value == 1.0


@pytest.mark.asyncio
async def test_solana_largest_accounts_keeps_provider_context():
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "context": {"slot": 1234},
            "value": [
                {
                    "address": "holder-1",
                    "amount": "100",
                    "decimals": 6,
                    "uiAmountString": "0.0001",
                }
            ],
        },
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))

    async with httpx.AsyncClient(transport=transport) as client:
        evidence = await SolanaEvidenceProvider(client, rpc_url="https://rpc.test").largest_accounts(
            mint_address="So11111111111111111111111111111111111111112"
        )

    assert evidence.status == "observed"
    assert evidence.provider == "solana_rpc"
    assert evidence.block_number == 1234
    assert evidence.value[0]["address"] == "holder-1"


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.getenv("POLYBOB_LIVE_PROVIDER_TESTS"),
    reason="live provider test",
)
async def test_live_alpha_schema_contains_identity_fields():
    async with build_provider_http_client() as client:
        tokens = await BinanceAlphaProvider(client).list_alpha_tokens("56")

    assert tokens
    assert all(token.contract_address and token.symbol for token in tokens)
