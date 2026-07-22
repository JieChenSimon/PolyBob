"""DEX Screener liquidity evidence provider."""

from __future__ import annotations

import httpx

from ..models import Evidence


class DexScreenerProvider:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        base_url: str = "https://api.dexscreener.com",
    ) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")

    async def token_pairs(self, chain_id: str, contract_address: str) -> Evidence:
        response = await self.client.get(
            f"{self.base_url}/token-pairs/v1/{chain_id}/{contract_address}"
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("DEX Screener token-pairs schema error")
        return Evidence(
            name="dex_pairs",
            value=payload,
            status="observed",
            provider="dex_screener",
            field="token-pairs",
        )
