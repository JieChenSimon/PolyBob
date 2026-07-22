"""Binance Web3 Alpha and smart-money provider."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx

from ..models import AlphaToken, Evidence, MarketCandle


ALPHA_RANK_PATH = (
    "/bapi/defi/v1/public/wallet-direct/buw/wallet/market/token/pulse/"
    "unified/rank/list/ai"
)
SMART_MONEY_PATH = (
    "/bapi/defi/v1/public/wallet-direct/tracker/wallet/token/inflow/rank/query/ai"
)
SMART_MONEY_CHAINS = frozenset({"56", "8453", "CT_501"})
ALPHA_TOKEN_LIST_PATH = "/bapi/defi/v1/public/wallet-direct/buw/wallet/cex/alpha/all/token/list"
ALPHA_KLINES_PATH = "/bapi/defi/v1/public/alpha-trade/klines"


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    number = _float_or_none(value)
    return int(number) if number is not None else None


def _has_alpha_tag(tags: Any) -> bool:
    if isinstance(tags, dict):
        return any(_has_alpha_tag(value) for value in tags.values())
    if isinstance(tags, list):
        return any(_has_alpha_tag(value) for value in tags)
    if isinstance(tags, str):
        return tags.casefold() == "alpha"
    return False


class BinanceAlphaProvider:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        base_url: str = "https://web3.binance.com",
        market_base_url: str = "https://www.binance.com",
    ) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.market_base_url = market_base_url.rstrip("/")
        self._alpha_ids: dict[tuple[str, str], str] | None = None
        self._alpha_ids_lock = asyncio.Lock()

    async def list_alpha_tokens(
        self,
        chain_id: str,
        *,
        page_size: int = 200,
    ) -> list[AlphaToken]:
        alpha_ids = self._alpha_ids or {}
        page = 1
        tokens: list[AlphaToken] = []
        while True:
            response = await self.client.post(
                f"{self.base_url}{ALPHA_RANK_PATH}",
                json={
                    "chainId": chain_id,
                    "rankType": 20,
                    "period": 50,
                    "page": page,
                    "size": page_size,
                    "countMin": 0,
                    "launchTimeMin": 0,
                    "liquidityMin": 0,
                    "uniqueTraderMin": 0,
                    "volumeMin": 0,
                },
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") != "000000" or not isinstance(payload.get("data"), dict):
                raise ValueError(f"Binance Alpha schema error for chain {chain_id}")
            data = payload["data"]
            observed_at = datetime.now(timezone.utc)
            for raw in data.get("tokens") or []:
                if not isinstance(raw, dict) or not _has_alpha_tag(raw.get("tokenTag")):
                    continue
                meta = raw.get("metaInfo") if isinstance(raw.get("metaInfo"), dict) else {}
                audit = raw.get("auditInfo") if isinstance(raw.get("auditInfo"), dict) else {}
                tokens.append(
                    AlphaToken(
                        chain_id=str(raw.get("chainId") or chain_id),
                        contract_address=str(raw.get("contractAddress") or ""),
                        symbol=str(raw.get("symbol") or ""),
                        alpha_id=alpha_ids.get(
                            (
                                str(raw.get("chainId") or chain_id),
                                str(raw.get("contractAddress") or "").casefold(),
                            )
                        ),
                        name=str(meta.get("name")) if meta.get("name") else None,
                        decimals=_int_or_none(meta.get("decimals") or raw.get("decimals")),
                        creator_address=meta.get("creatorAddress"),
                        is_alpha=True,
                        blacklisted=bool(meta.get("blacklist", False)),
                        price=_float_or_none(raw.get("price")),
                        market_cap=_float_or_none(raw.get("marketCap")),
                        liquidity=_float_or_none(raw.get("liquidity")),
                        volume_24h=_float_or_none(raw.get("volume24h")),
                        volume_24h_buy=_float_or_none(raw.get("volume24hBuy")),
                        volume_24h_sell=_float_or_none(raw.get("volume24hSell")),
                        holders=_int_or_none(raw.get("holders")),
                        holders_top10_percent=_float_or_none(raw.get("holdersTop10Percent")),
                        launch_time_ms=_int_or_none(raw.get("launchTime")),
                        audit_risk_level=_int_or_none(audit.get("riskLevel")),
                        audit_risk_codes=[str(code) for code in audit.get("riskCodes") or []],
                        token_tags=raw.get("tokenTag") or {},
                        raw=raw,
                        observed_at=observed_at,
                    )
                )
            total = int(data.get("total") or 0)
            size = int(data.get("size") or page_size)
            if page * size >= total:
                break
            page += 1
        return tokens

    async def _load_alpha_ids(self) -> dict[tuple[str, str], str]:
        if self._alpha_ids is not None:
            return self._alpha_ids
        async with self._alpha_ids_lock:
            if self._alpha_ids is not None:
                return self._alpha_ids
            response = await self.client.get(f"{self.market_base_url}{ALPHA_TOKEN_LIST_PATH}")
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") != "000000" or not isinstance(payload.get("data"), list):
                raise ValueError("Binance Alpha token-list schema error")
            self._alpha_ids = {
                (
                    str(row.get("chainId") or ""),
                    str(row.get("contractAddress") or "").casefold(),
                ): str(row["alphaId"])
                for row in payload["data"]
                if isinstance(row, dict) and row.get("alphaId") and row.get("contractAddress")
            }
            return self._alpha_ids

    async def klines(
        self,
        token: AlphaToken,
        *,
        interval: str = "1d",
        limit: int = 180,
    ) -> list[MarketCandle]:
        if not token.alpha_id:
            alpha_ids = await self._load_alpha_ids()
            token.alpha_id = alpha_ids.get((token.chain_id, token.contract_address.casefold()))
        if not token.alpha_id:
            return []
        response = await self.client.get(
            f"{self.market_base_url}{ALPHA_KLINES_PATH}",
            params={"symbol": f"{token.alpha_id}USDT", "interval": interval, "limit": limit},
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != "000000" or not isinstance(payload.get("data"), list):
            raise ValueError("Binance Alpha klines schema error")
        candles: list[MarketCandle] = []
        for row in payload["data"]:
            if not isinstance(row, list) or len(row) < 6:
                raise ValueError("Binance Alpha kline row schema error")
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

    async def list_smart_money(self, chain_id: str, *, period: str = "24h") -> Evidence:
        if chain_id not in SMART_MONEY_CHAINS:
            return Evidence(
                name="smart_money_inflow",
                value=None,
                status="unsupported",
                provider="binance_web3",
                detail=f"Smart-money rank is not supported for chain {chain_id}",
            )

        response = await self.client.post(
            f"{self.base_url}{SMART_MONEY_PATH}",
            json={"chainId": chain_id, "period": period, "tagType": 2},
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != "000000" or not isinstance(payload.get("data"), list):
            raise ValueError(f"Binance smart-money schema error for chain {chain_id}")
        return Evidence(
            name="smart_money_inflow",
            value=payload["data"],
            status="observed",
            provider="binance_web3",
            field="data[].inflow",
        )
