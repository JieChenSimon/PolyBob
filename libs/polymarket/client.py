"""
Polymarket API 客户端
"""
import httpx
import structlog
from typing import Any

logger = structlog.get_logger()


class PolymarketClient:
    """Polymarket REST API 客户端"""

    def __init__(self, base_url: str, api_key: str = ""):
        self.base_url = base_url
        self.api_key = api_key
        self.client = httpx.AsyncClient(
            base_url=base_url,
            timeout=30.0,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        )

    async def get_markets(
        self,
        limit: int = 100,
        offset: int = 0,
        active: bool = True,
        closed: bool | None = None,
    ) -> list[dict[str, Any]]:
        """获取市场列表"""
        try:
            params = {
                "limit": limit,
                "offset": offset,
                "active": str(active).lower(),
            }
            if closed is not None:
                params["closed"] = str(closed).lower()

            response = await self.client.get(
                "/markets",
                params=params,
            )
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and isinstance(data.get("data"), list):
                markets = data["data"]
            elif isinstance(data, list):
                markets = data
            else:
                logger.error("unexpected_markets_response", response_type=type(data).__name__)
                raise ValueError("Unexpected markets response shape")

            logger.info("fetched_markets", count=len(markets))
            return markets
        except Exception as e:
            logger.error("failed_to_fetch_markets", error=str(e))
            raise

    async def get_market(self, market_id: str) -> dict[str, Any]:
        """获取单个市场信息"""
        try:
            response = await self.client.get(f"/markets/{market_id}")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error("failed_to_fetch_market", market_id=market_id, error=str(e))
            raise

    async def get_orderbook(self, token_id: str) -> dict[str, Any]:
        """获取订单簿快照"""
        try:
            response = await self.client.get(
                "/book",
                params={"token_id": token_id},
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error("failed_to_fetch_orderbook", token_id=token_id, error=str(e))
            raise

    async def get_trades(
        self,
        market_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """获取成交记录"""
        try:
            response = await self.client.get(
                f"/trades/{market_id}",
                params={"limit": limit},
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error("failed_to_fetch_trades", market_id=market_id, error=str(e))
            raise

    async def close(self):
        """关闭客户端"""
        await self.client.aclose()
