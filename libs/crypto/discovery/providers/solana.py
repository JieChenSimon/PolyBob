"""Solana RPC evidence used by the discovery workbench."""

from __future__ import annotations

import httpx

from ..models import Evidence


class SolanaEvidenceProvider:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        rpc_url: str = "https://api.mainnet-beta.solana.com",
    ) -> None:
        self.client = client
        self.rpc_url = rpc_url

    async def largest_accounts(self, *, mint_address: str) -> Evidence:
        response = await self.client.post(
            self.rpc_url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenLargestAccounts",
                "params": [mint_address, {"commitment": "finalized"}],
            },
        )
        response.raise_for_status()
        payload = response.json()
        result = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(result, dict) or not isinstance(result.get("value"), list):
            raise ValueError("Solana RPC largest-accounts schema error")
        context = result.get("context") if isinstance(result.get("context"), dict) else {}
        return Evidence(
            name="largest_accounts",
            value=result["value"],
            status="observed",
            provider="solana_rpc",
            field="getTokenLargestAccounts",
            block_number=int(context["slot"]) if context.get("slot") is not None else None,
            metadata={"mint_address": mint_address},
        )
