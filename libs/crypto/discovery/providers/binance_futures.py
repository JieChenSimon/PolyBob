"""Binance USD-M public market-data provider."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import re
from typing import Any, Awaitable, Callable

import httpx
from websockets.asyncio.client import connect

from libs.networking import resolve_outbound_proxy
from ..models import FuturesContract, FuturesMarketSignals, MarketCandle


WebsocketRequest = Callable[[str, dict[str, Any]], Awaitable[Any]]
_CANONICAL_USDT_PERPETUAL = re.compile(r"^[A-Z0-9]+USDT$")


class BinanceFuturesProvider:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        base_url: str = "https://fapi.binance.com",
        websocket_url: str = "wss://ws-fapi.binance.com/ws-fapi/v1",
        proxy: str | None = None,
        websocket_request: WebsocketRequest | None = None,
    ) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.websocket_url = websocket_url
        self.proxy = proxy
        self._websocket_request = websocket_request or self._request_websocket
        self.last_transport = "rest"
        self._websocket_prices: dict[str, float] = {}

    async def list_perpetuals(self) -> list[FuturesContract]:
        try:
            response = await self.client.get(f"{self.base_url}/fapi/v1/exchangeInfo")
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPStatusError, httpx.TransportError) as rest_error:
            try:
                payload = await self._websocket_request("ticker.price", {})
            except Exception as websocket_error:
                raise RuntimeError(
                    f"Binance Futures REST failed ({rest_error}); official WebSocket fallback "
                    f"failed ({websocket_error})"
                ) from websocket_error
            self.last_transport = "websocket_api_inferred_perpetual"
            contracts = _contracts_from_websocket_tickers(payload)
            self._websocket_prices = {
                contract.symbol: contract.price
                for contract in contracts
                if contract.price is not None
            }
            return contracts

        self.last_transport = "rest_exchange_info"
        if not isinstance(payload, dict) or not isinstance(payload.get("symbols"), list):
            raise ValueError("Binance Futures exchangeInfo schema error")

        observed_at = datetime.now(timezone.utc)
        contracts: list[FuturesContract] = []
        for raw in payload["symbols"]:
            if not isinstance(raw, dict):
                continue
            if not (
                raw.get("contractType") == "PERPETUAL"
                and raw.get("status") == "TRADING"
                and raw.get("quoteAsset") == "USDT"
            ):
                continue
            contracts.append(
                FuturesContract(
                    symbol=str(raw["symbol"]),
                    base_asset=str(raw["baseAsset"]),
                    quote_asset="USDT",
                    status="TRADING",
                    contract_type="PERPETUAL",
                    price_precision=_int_or_none(raw.get("pricePrecision")),
                    quantity_precision=_int_or_none(raw.get("quantityPrecision")),
                    quantity_step=_lot_size_step(raw.get("filters")),
                    observed_at=observed_at,
                )
            )
        return contracts

    async def _request_websocket(self, method: str, params: dict[str, Any]) -> Any:
        proxy = self.proxy if self.proxy is not None else resolve_outbound_proxy()
        async with connect(
            self.websocket_url,
            proxy=proxy or True,
            open_timeout=10,
            close_timeout=2,
        ) as websocket:
            await websocket.send(json.dumps({"id": 1, "method": method, "params": params}))
            payload = json.loads(await asyncio.wait_for(websocket.recv(), timeout=10))
        if not isinstance(payload, dict) or payload.get("status") != 200:
            raise ValueError(f"Binance Futures WebSocket API error: {payload}")
        return payload.get("result")

    async def klines(
        self,
        symbol: str,
        *,
        interval: str = "1d",
        limit: int = 180,
    ) -> list[MarketCandle]:
        response = await self.client.get(
            f"{self.base_url}/fapi/v1/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("Binance Futures klines schema error")
        candles: list[MarketCandle] = []
        for row in payload:
            if not isinstance(row, list) or len(row) < 6:
                raise ValueError("Binance Futures kline row schema error")
            candles.append(
                MarketCandle(
                    open_time_ms=int(row[0]),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                    close_time_ms=int(row[6]) if len(row) > 6 else None,
                    trade_count=int(row[8]) if len(row) > 8 else None,
                )
            )
        return candles

    async def market_signals(self, symbol: str) -> FuturesMarketSignals:
        if self.last_transport == "websocket_api_inferred_perpetual":
            price = self._websocket_prices.get(symbol)
            if price is None:
                raise ValueError(f"Binance Futures WebSocket price unavailable for {symbol}")
            return FuturesMarketSignals(symbol=symbol, price=price)

        ticker_response, premium_response, interest_response, positioning_response = (
            await asyncio.gather(
                self.client.get(
                    f"{self.base_url}/fapi/v1/ticker/24hr",
                    params={"symbol": symbol},
                ),
                self.client.get(
                    f"{self.base_url}/fapi/v1/premiumIndex",
                    params={"symbol": symbol},
                ),
                self.client.get(
                    f"{self.base_url}/futures/data/openInterestHist",
                    params={"symbol": symbol, "period": "1d", "limit": 30},
                ),
                self.client.get(
                    f"{self.base_url}/futures/data/globalLongShortAccountRatio",
                    params={"symbol": symbol, "period": "1d", "limit": 30},
                ),
            )
        )
        for response in (
            ticker_response,
            premium_response,
            interest_response,
            positioning_response,
        ):
            response.raise_for_status()

        ticker = ticker_response.json()
        premium = premium_response.json()
        interest = interest_response.json()
        positioning = positioning_response.json()
        if not isinstance(ticker, dict) or not isinstance(premium, dict):
            raise ValueError("Binance Futures signal schema error")

        interest_change = None
        if isinstance(interest, list) and len(interest) >= 2:
            first = float(interest[0]["sumOpenInterestValue"])
            last = float(interest[-1]["sumOpenInterestValue"])
            interest_change = last / first - 1.0 if first > 0 else None

        long_short_ratio = None
        if isinstance(positioning, list) and positioning:
            long_short_ratio = float(positioning[-1]["longShortRatio"])

        return FuturesMarketSignals(
            symbol=symbol,
            price=float(ticker["lastPrice"]),
            volume_24h_usd=float(ticker["quoteVolume"]),
            funding_rate=float(premium["lastFundingRate"]),
            open_interest_change=interest_change,
            long_short_ratio=long_short_ratio,
        )


def _contracts_from_websocket_tickers(payload: Any) -> list[FuturesContract]:
    if not isinstance(payload, list):
        raise ValueError("Binance Futures WebSocket ticker schema error")
    observed_at = datetime.now(timezone.utc)
    contracts: list[FuturesContract] = []
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        symbol = str(raw.get("symbol") or "")
        if not _CANONICAL_USDT_PERPETUAL.fullmatch(symbol):
            continue
        try:
            if float(raw["price"]) <= 0:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        contracts.append(
            FuturesContract(
                symbol=symbol,
                base_asset=symbol[:-4],
                price=float(raw["price"]),
                quote_asset="USDT",
                status="TRADING",
                contract_type="PERPETUAL",
                observed_at=observed_at,
            )
        )
    return contracts

def _lot_size_step(filters: Any) -> float | None:
    if not isinstance(filters, list):
        return None
    for item in filters:
        if isinstance(item, dict) and item.get("filterType") == "LOT_SIZE":
            try:
                return float(item["stepSize"])
            except (KeyError, TypeError, ValueError):
                return None
    return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
