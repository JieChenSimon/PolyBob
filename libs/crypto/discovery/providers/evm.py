"""Minimal EVM RPC evidence used by the discovery workbench."""

from __future__ import annotations

import httpx

from ..models import Evidence


DEFAULT_EVM_RPC_URLS = {
    "1": "https://ethereum-rpc.publicnode.com",
    "56": "https://bsc-rpc.publicnode.com",
    "8453": "https://base-rpc.publicnode.com",
}


class EvmEvidenceProvider:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        rpc_urls: dict[str, str] | None = None,
    ) -> None:
        self.client = client
        self.rpc_urls = rpc_urls or DEFAULT_EVM_RPC_URLS

    async def token_supply(
        self,
        *,
        chain_id: str,
        contract_address: str,
        decimals: int,
    ) -> Evidence:
        rpc_url = self.rpc_urls.get(chain_id)
        if rpc_url is None:
            return Evidence(
                name="token_supply",
                status="unsupported",
                provider="evm_rpc",
                detail=f"No EVM RPC configured for chain {chain_id}",
            )
        block_hex = await self._rpc(rpc_url, "eth_blockNumber", [])
        supply_hex = await self._rpc(
            rpc_url,
            "eth_call",
            [{"to": contract_address, "data": "0x18160ddd"}, "latest"],
        )
        return Evidence(
            name="token_supply",
            value=int(supply_hex, 16) / (10**decimals),
            status="observed",
            provider="evm_rpc",
            field="totalSupply",
            block_number=int(block_hex, 16),
            metadata={"chain_id": chain_id, "contract_address": contract_address},
        )

    async def _rpc(self, url: str, method: str, params: list[object]) -> str:
        response = await self.client.post(
            url,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        )
        response.raise_for_status()
        payload = response.json()
        result = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(result, str):
            raise ValueError(f"EVM RPC schema error for {method}")
        return result
