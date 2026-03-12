"""
Market Discovery Service - 市场发现服务

职责：
- 从 Polymarket 获取新增市场、活跃市场、临近结算市场
- 维护 watchlist
- 识别市场分组、互斥市场、条件市场和高相关市场
"""
import asyncio
import structlog
from datetime import datetime
from typing import Set

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
        self._running = False

    async def start(self):
        """启动服务"""
        logger.info("starting_market_discovery_service")
        self._running = True

        # 启动定期扫描任务
        asyncio.create_task(self._scan_markets_loop())

    async def stop(self):
        """停止服务"""
        logger.info("stopping_market_discovery_service")
        self._running = False
        await self.client.close()

    async def _scan_markets_loop(self):
        """定期扫描市场"""
        while self._running:
            try:
                await self._scan_markets()
            except Exception as e:
                logger.error("market_scan_error", error=str(e), exc_info=True)

            # 每5分钟扫描一次
            await asyncio.sleep(300)

    async def _scan_markets(self):
        """扫描市场"""
        logger.info("scanning_markets")

        # 获取活跃市场
        markets_data = await self.client.get_markets(limit=100, active=True)

        discovered_count = 0
        updated_count = 0

        for market_data in markets_data:
            if not self._is_tradeable_market(market_data):
                continue

            market_id = str(market_data.get("id", ""))
            if not market_id:
                continue

            # 转换为内部模型
            market = self._parse_market(market_data)

            # 检查是否是新市场
            if market_id not in self.watchlist:
                discovered_count += 1
                self.watchlist.add(market_id)

                # 发布市场发现事件
                await self.event_bus.publish(Topics.MARKET_DISCOVERED, market)

                logger.info(
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

        return active and not closed and not archived

    def _parse_market(self, data: dict) -> Market:
        """解析市场数据"""
        active = bool(data.get("active", False))
        closed = bool(data.get("closed", False))
        archived = bool(data.get("archived", False))

        if archived:
            status = MarketStatus.SUSPENDED
        elif closed:
            status = MarketStatus.CLOSED
        elif active:
            status = MarketStatus.ACTIVE
        else:
            status = MarketStatus.SUSPENDED

        return Market(
            market_id=str(data["id"]),
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
            created_at=self._parse_datetime(
                data.get("createdAt") or data.get("created_at")
            ) or datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

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

    async def add_to_watchlist(self, market_id: str):
        """添加到 watchlist"""
        self.watchlist.add(market_id)
        logger.info("added_to_watchlist", market_id=market_id)

    async def remove_from_watchlist(self, market_id: str):
        """从 watchlist 移除"""
        self.watchlist.discard(market_id)
        logger.info("removed_from_watchlist", market_id=market_id)
