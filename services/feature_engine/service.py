"""
Feature Engine Service - 特征引擎服务

职责：
- 将原始流数据聚合为可交易特征
- 按 1 秒、5 秒、1 分钟等窗口持续更新
- 形成策略输入层
"""
import asyncio
import structlog
from datetime import datetime, timedelta
from collections import defaultdict, deque
from typing import Dict, Optional
import numpy as np

from libs.events import get_event_bus, Topics
from libs.schemas import OrderbookTick, TradeTick
from libs.terminal_status import render_status

logger = structlog.get_logger()


class MarketFeatures:
    """市场特征 - 优化版本"""

    def __init__(self, market_id: str):
        self.market_id = market_id
        self.last_update = datetime.utcnow()

        # 盘口特征
        self.mid_price = 0.0
        self.spread_bps = 0.0
        self.bid_price = 0.0
        self.ask_price = 0.0
        self.bid_size = 0.0
        self.ask_size = 0.0
        self.depth_imbalance = 0.0

        # 成交特征
        self.trade_intensity_1m = 0.0
        self.volume_1m = 0.0
        self.price_jump_score = 0.0

        # 历史数据
        self.recent_trades: deque = deque(maxlen=100)
        self.price_history: deque = deque(maxlen=60)

        # 缓存优化
        self._cached_features: Optional[dict] = None
        self._cache_timestamp: Optional[datetime] = None
        self._cache_ttl = timedelta(milliseconds=100)  # 100ms缓存

        # 增量计算状态
        self._running_sum = 0.0
        self._running_sum_sq = 0.0
        self._price_count = 0

    def update_from_orderbook(self, orderbook: OrderbookTick):
        """从订单簿更新特征 - 优化版本"""
        self.last_update = orderbook.timestamp
        self.bid_price = orderbook.bid_price
        self.ask_price = orderbook.ask_price
        self.bid_size = orderbook.bid_size
        self.ask_size = orderbook.ask_size

        if self.bid_price > 0 and self.ask_price > 0:
            self.mid_price = (self.bid_price + self.ask_price) * 0.5
            self.spread_bps = (self.ask_price - self.bid_price) / self.mid_price * 10000

            total_depth = self.bid_size + self.ask_size
            if total_depth > 0:
                self.depth_imbalance = (self.bid_size - self.ask_size) / total_depth

            self.price_history.append((orderbook.timestamp, self.mid_price))
            self._update_price_stats_incremental(self.mid_price)
            self._calculate_price_jump_fast()

        self._invalidate_cache()

    def update_from_trade(self, trade: TradeTick):
        """从成交记录更新特征 - 优化版本"""
        self.recent_trades.append(trade)
        cutoff_time = datetime.utcnow() - timedelta(minutes=1)

        # 增量更新：只处理新增交易
        self.trade_intensity_1m = sum(1 for t in self.recent_trades if t.timestamp > cutoff_time)
        self.volume_1m = sum(t.size for t in self.recent_trades if t.timestamp > cutoff_time)
        self._invalidate_cache()

    def _update_price_stats_incremental(self, new_price: float):
        """增量更新价格统计"""
        self._running_sum += new_price
        self._running_sum_sq += new_price * new_price
        self._price_count += 1

        if self._price_count > 60:
            old_price = self.price_history[0][1]
            self._running_sum -= old_price
            self._running_sum_sq -= old_price * old_price
            self._price_count -= 1

    def _calculate_price_jump_fast(self):
        """快速计算价格跳变分数 - 使用增量统计"""
        if self._price_count < 2:
            self.price_jump_score = 0.0
            return

        mean_price = self._running_sum / self._price_count
        variance = (self._running_sum_sq / self._price_count) - (mean_price * mean_price)

        if variance <= 0:
            self.price_jump_score = 0.0
            return

        std_dev = np.sqrt(variance)
        if std_dev > 0:
            self.price_jump_score = abs(self.mid_price - mean_price) / std_dev
        else:
            self.price_jump_score = 0.0

    def _invalidate_cache(self):
        """使缓存失效"""
        self._cached_features = None
        self._cache_timestamp = None

    def to_dict(self) -> dict:
        """转换为字典 - 带缓存优化"""
        now = datetime.utcnow()
        if self._cached_features and self._cache_timestamp:
            if now - self._cache_timestamp < self._cache_ttl:
                return self._cached_features

        self._cached_features = {
            "market_id": self.market_id,
            "timestamp": self.last_update,
            "mid_price": self.mid_price,
            "spread_bps": self.spread_bps,
            "bid_price": self.bid_price,
            "ask_price": self.ask_price,
            "bid_size": self.bid_size,
            "ask_size": self.ask_size,
            "depth_imbalance": self.depth_imbalance,
            "trade_intensity_1m": self.trade_intensity_1m,
            "volume_1m": self.volume_1m,
            "price_jump_score": self.price_jump_score,
        }
        self._cache_timestamp = now
        return self._cached_features


class FeatureEngineService:
    """特征引擎服务"""

    def __init__(self):
        self.event_bus = get_event_bus()
        self.features: Dict[str, MarketFeatures] = {}
        self._running = False

        # 异常阈值
        self.spread_threshold_bps = 200.0  # 价差超过200bps告警
        self.price_jump_threshold = 3.0  # 价格跳变超过3个标准差告警
        self.alert_cooldown = timedelta(seconds=30)
        self._last_alert_at: Dict[tuple[str, str], datetime] = {}

    async def start(self):
        """启动服务"""
        logger.info("starting_feature_engine_service")
        self._running = True

        # 订阅市场数据事件
        await self.event_bus.subscribe(Topics.ORDERBOOK_TICK, self._on_orderbook_tick)
        await self.event_bus.subscribe(Topics.TRADE_TICK, self._on_trade_tick)

        # 启动定期快照任务
        asyncio.create_task(self._snapshot_loop())

    async def stop(self):
        """停止服务"""
        logger.info("stopping_feature_engine_service")
        self._running = False

    async def _on_orderbook_tick(self, orderbook: OrderbookTick):
        """处理订单簿更新"""
        market_id = orderbook.market_id

        # 获取或创建特征对象
        if market_id not in self.features:
            self.features[market_id] = MarketFeatures(market_id)

        # 更新特征
        features = self.features[market_id]
        features.update_from_orderbook(orderbook)

        # 检查异常
        await self._check_anomalies(features)

    async def _on_trade_tick(self, trade: TradeTick):
        """处理成交记录"""
        market_id = trade.market_id

        if market_id not in self.features:
            self.features[market_id] = MarketFeatures(market_id)

        # 更新特征
        features = self.features[market_id]
        features.update_from_trade(trade)

    async def _check_anomalies(self, features: MarketFeatures):
        """检查异常"""
        alerts = []

        # 检查价差异常
        if features.spread_bps > self.spread_threshold_bps:
            alerts.append({
                "type": "spread_anomaly",
                "market_id": features.market_id,
                "spread_bps": features.spread_bps,
                "threshold": self.spread_threshold_bps,
            })

        # 检查价格跳变
        if features.price_jump_score > self.price_jump_threshold:
            alerts.append({
                "type": "price_jump",
                "market_id": features.market_id,
                "jump_score": features.price_jump_score,
                "threshold": self.price_jump_threshold,
            })

        # 发布告警
        for alert in alerts:
            alert_key = (str(alert["market_id"]), str(alert["type"]))
            last_alert_at = self._last_alert_at.get(alert_key)
            now = datetime.utcnow()
            if last_alert_at and now - last_alert_at < self.alert_cooldown:
                continue

            self._last_alert_at[alert_key] = now
            await self.event_bus.publish(Topics.FEATURE_ALERT, alert)
            logger.debug("feature_alert", **alert)
            if alert["type"] == "spread_anomaly":
                render_status(
                    f"alert spread_anomaly: {features.market_id[:12]}... spread={features.spread_bps:.1f}bps"
                )
            elif alert["type"] == "price_jump":
                render_status(
                    f"alert price_jump: {features.market_id[:12]}... score={features.price_jump_score:.2f}"
                )

    async def _snapshot_loop(self):
        """定期发布特征快照"""
        while self._running:
            try:
                # 发布所有市场的特征快照
                for features in self.features.values():
                    await self.event_bus.publish(
                        Topics.FEATURE_SNAPSHOT,
                        features.to_dict(),
                    )

                logger.debug("published_feature_snapshots", count=len(self.features))

            except Exception as e:
                logger.error("snapshot_loop_error", error=str(e), exc_info=True)

            # 每5秒发布一次
            await asyncio.sleep(5)

    def get_features(self, market_id: str) -> MarketFeatures | None:
        """获取市场特征"""
        return self.features.get(market_id)
