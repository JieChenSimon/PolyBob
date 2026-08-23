"""
Market Discovery Service - 市场发现服务

职责：
- 从 Polymarket 获取新增市场、活跃市场、临近结算市场
- 维护 watchlist
- 识别市场分组、互斥市场、条件市场和高相关市场
"""
import asyncio
import json
import httpx
import structlog
from datetime import datetime
from typing import Dict, Set

from libs.polymarket import PolymarketClient
from libs.events import get_event_bus, Topics
from libs.schemas import Market, MarketStatus
from libs.config import get_settings

logger = structlog.get_logger()


class MarketDiscoveryService:
    """市场发现服务"""

    def __init__(self):
        self.settings = get_settings()
        self.client = PolymarketClient(
            base_url=self.settings.polymarket_gamma_api_url,
            api_key=self.settings.polymarket_api_key,
        )
        self.event_bus = get_event_bus()
        self.watchlist: Set[str] = set()
        self.markets: Dict[str, Market] = {}
        self._running = False
        self._scan_task: asyncio.Task | None = None

    async def start(self):
        """启动服务"""
        logger.info("starting_market_discovery_service")
        self._running = True

        # 启动定期扫描任务
        self._scan_task = asyncio.create_task(self._scan_markets_loop())

    async def stop(self):
        """停止服务"""
        logger.info("stopping_market_discovery_service")
        self._running = False
        if self._scan_task is not None:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass
            self._scan_task = None
        await self.client.close()

    async def _scan_markets_loop(self):
        """定期扫描市场"""
        while self._running:
            try:
                await self._scan_markets()
            except Exception as e:
                error_category = classify_market_scan_error(e)
                if error_category:
                    logger.warning(
                        "market_scan_external_unavailable",
                        category=error_category,
                        error=str(e) or e.__class__.__name__,
                        retry_after_seconds=300,
                    )
                else:
                    logger.error("market_scan_error", error=str(e), exc_info=True)

            # 每5分钟扫描一次
            await asyncio.sleep(300)

    async def _scan_markets(self):
        """扫描市场"""
        logger.info("scanning_markets")

        # 获取活跃市场
        markets_data = await self.client.get_markets(limit=100, active=True, closed=False)

        discovered_count = 0
        updated_count = 0

        for market_data in markets_data:
            if not self._running:
                break

            if not self._is_tradeable_market(market_data):
                continue

            market = self._parse_market(market_data)
            market_id = market.market_id
            if not market_id:
                continue

            self.markets[market_id] = market

            # 检查是否是新市场
            if market_id not in self.watchlist:
                discovered_count += 1
                self.watchlist.add(market_id)

                # 发布市场发现事件
                await self.event_bus.publish(Topics.MARKET_DISCOVERED, market)

                logger.debug(
                    "market_discovered",
                    market_id=market_id,
                    question=market.question,
                )
            else:
                updated_count += 1

        logger.info(
            "market_scan_completed",
            total=len(markets_data),
            discovered=discovered_count,
            updated=updated_count,
            watchlist_size=len(self.watchlist),
        )

        # 发布 watchlist 更新事件
        await self.event_bus.publish(
            Topics.MARKET_WATCHLIST_UPDATED,
            {"watchlist": list(self.watchlist), "timestamp": datetime.utcnow()},
        )

    def _is_tradeable_market(self, data: dict) -> bool:
        """判断市场是否适合加入 watchlist"""
        active = bool(data.get("active", False))
        closed = bool(data.get("closed", False))
        archived = bool(data.get("archived", False))
        enable_orderbook = bool(
            data.get("enableOrderBook", data.get("enable_order_book", False))
        )
        token_ids = self._parse_token_ids(data)

        return active and not closed and not archived and enable_orderbook and bool(token_ids)

    def _parse_market(self, data: dict) -> Market:
        """解析市场数据"""
        active = bool(data.get("active", False))
        closed = bool(data.get("closed", False))
        archived = bool(data.get("archived", False))
        token_ids = self._parse_token_ids(data)

        if archived:
            status = MarketStatus.SUSPENDED
        elif closed:
            status = MarketStatus.CLOSED
        elif active:
            status = MarketStatus.ACTIVE
        else:
            status = MarketStatus.SUSPENDED

        return Market(
            market_id=str(data.get("conditionId") or data.get("condition_id") or ""),
            gamma_market_id=str(data["id"]),
            slug=data.get("slug", ""),
            question=data.get("question", ""),
            category=data.get("category"),
            status=status,
            end_time=self._parse_datetime(
                data.get("endDate") or data.get("endDateIso") or data.get("end_time")
            ),
            liquidity_score=float(
                data.get("liquidityNum", data.get("liquidity", 0.0)) or 0.0
            ),
            clob_token_ids=token_ids,
            primary_asset_id=token_ids[0] if token_ids else None,
            created_at=self._parse_datetime(
                data.get("createdAt") or data.get("created_at")
            ) or datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

    def _parse_token_ids(self, data: dict) -> list[str]:
        """从 Gamma 市场对象中解析 CLOB token ids"""
        raw = data.get("clobTokenIds") or data.get("clob_token_ids")
        if isinstance(raw, str) and raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return [str(token_id) for token_id in parsed if token_id]
            except json.JSONDecodeError:
                logger.warning("failed_to_parse_clob_token_ids", raw_value=raw)

        tokens = data.get("tokens", [])
        if isinstance(tokens, list):
            token_ids: list[str] = []
            for token in tokens:
                if not isinstance(token, dict):
                    continue
                token_id = token.get("token_id") or token.get("tokenId")
                if token_id:
                    token_ids.append(str(token_id))
            return token_ids

        return []

    def _parse_datetime(self, value: str | None) -> datetime | None:
        """兼容 ISO 8601 日期时间格式"""
        if not value:
            return None

        normalized = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            return None

    async def get_watchlist(self) -> list[str]:
        """获取 watchlist"""
        return list(self.watchlist)

    async def get_markets(self, limit: int | None = None) -> list[Market]:
        """获取 watchlist 中的市场元数据"""
        markets = [
            self.markets[market_id]
            for market_id in self.watchlist
            if market_id in self.markets
        ]
        markets.sort(key=lambda market: market.liquidity_score, reverse=True)
        if limit is not None:
            return markets[:limit]
        return markets

    async def get_market(self, market_id: str) -> Market | None:
        """获取单个市场元数据"""
        return self.markets.get(market_id)

    async def add_to_watchlist(self, market_id: str):
        """添加到 watchlist"""
        self.watchlist.add(market_id)
        logger.debug("added_to_watchlist", market_id=market_id)

    async def remove_from_watchlist(self, market_id: str):
        """从 watchlist 移除"""
        self.watchlist.discard(market_id)
        logger.debug("removed_from_watchlist", market_id=market_id)


def classify_market_scan_error(exc: Exception) -> str | None:
    message = str(exc).lower()
    if isinstance(exc, httpx.ProxyError) or "proxy" in message:
        if "503" in message or "service unavailable" in message:
            return "proxy_503"
        return "proxy_error"
    if isinstance(exc, httpx.TimeoutException):
        return "network_timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        if status_code == 429:
            return "provider_rate_limit"
        if status_code >= 500:
            return "provider_5xx"
        return None
    if isinstance(exc, httpx.TransportError):
        return "network_transport"
    if "503" in message or "service unavailable" in message:
        return "provider_or_proxy_503"
    return None
