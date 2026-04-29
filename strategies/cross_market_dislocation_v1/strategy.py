"""
Cross Market Dislocation Strategy V1 - 跨市场错位套利

核心逻辑:
- 监控相关市场间的价格差异
- 当价差超过历史均值 + N 个标准差时触发信号
- 统计套利,均值回归假设
"""
import asyncio
import structlog
from datetime import datetime
from collections import defaultdict, deque
from typing import Dict
import uuid

from libs.events import get_event_bus, Topics
from libs.schemas import Signal, Side

logger = structlog.get_logger()


class CrossMarketDislocationV1:
    """跨市场错位套利策略"""

    def __init__(self, config: dict):
        self.strategy_id = "cross_market_dislocation_v1"
        self.event_bus = get_event_bus()

        # 配置参数
        self.z_score_threshold = config.get("z_score_threshold", 2.0)
        self.min_spread_bps = config.get("min_spread_bps", 50.0)
        self.lookback_window = config.get("lookback_window", 100)
        self.signal_ttl = config.get("signal_ttl_seconds", 300)

        # 市场特征缓存
        self.features: Dict[str, dict] = {}

        # 价差历史 (market_pair -> deque of spreads)
        self.spread_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.lookback_window))

        self._running = False

    async def start(self):
        """启动策略"""
        logger.info("starting_strategy", strategy_id=self.strategy_id)
        self._running = True

        # 订阅特征快照
        await self.event_bus.subscribe(Topics.FEATURE_SNAPSHOT, self._on_feature_snapshot)

    async def stop(self):
        """停止策略"""
        logger.info("stopping_strategy", strategy_id=self.strategy_id)
        self._running = False

    async def _on_feature_snapshot(self, feature_data: dict):
        """处理特征快照"""
        market_id = feature_data["market_id"]
        self.features[market_id] = feature_data

        # 检查所有市场对的价差
        await self._check_market_pairs()

    async def _check_market_pairs(self):
        """检查市场对价差"""
        market_ids = list(self.features.keys())

        # 遍历所有市场对
        for i in range(len(market_ids)):
            for j in range(i + 1, len(market_ids)):
                market_a = market_ids[i]
                market_b = market_ids[j]

                await self._analyze_pair(market_a, market_b)

    async def _analyze_pair(self, market_a: str, market_b: str):
        """分析市场对"""
        features_a = self.features.get(market_a)
        features_b = self.features.get(market_b)

        if not features_a or not features_b:
            return

        # 计算价差
        price_a = features_a.get("mid_price", 0)
        price_b = features_b.get("mid_price", 0)

        if price_a <= 0 or price_b <= 0:
            return

        spread = price_a - price_b
        spread_bps = (spread / ((price_a + price_b) / 2)) * 10000

        # 记录价差历史
        pair_key = f"{market_a}:{market_b}"
        self.spread_history[pair_key].append(spread)

        # 需要足够的历史数据
        if len(self.spread_history[pair_key]) < 20:
            return

        # 计算 Z-score
        spreads = list(self.spread_history[pair_key])
        mean_spread = sum(spreads) / len(spreads)
        variance = sum((s - mean_spread) ** 2 for s in spreads) / len(spreads)
        std_dev = variance ** 0.5

        if std_dev == 0:
            return

        z_score = (spread - mean_spread) / std_dev

        # 生成信号
        if abs(z_score) > self.z_score_threshold and abs(spread_bps) > self.min_spread_bps:
            if z_score > 0:
                # 价差过大,做空 A,做多 B
                await self._generate_signal(market_a, Side.SELL_YES, features_a, z_score, spread_bps)
                await self._generate_signal(market_b, Side.BUY_YES, features_b, z_score, spread_bps)
            else:
                # 价差过小,做多 A,做空 B
                await self._generate_signal(market_a, Side.BUY_YES, features_a, z_score, spread_bps)
                await self._generate_signal(market_b, Side.SELL_YES, features_b, z_score, spread_bps)

    async def _generate_signal(self, market_id: str, side: Side, features: dict, z_score: float, spread_bps: float):
        """生成交易信号"""
        signal = Signal(
            signal_id=str(uuid.uuid4()),
            market_id=market_id,
            strategy_id=self.strategy_id,
            timestamp=datetime.utcnow(),
            side=side,
            price=features["mid_price"],
            size=100.0,  # 固定仓位,后续由风控调整
            expected_edge_bps=abs(spread_bps) / 2,  # 预期优势为价差的一半
            confidence=min(abs(z_score) / 5.0, 1.0),  # Z-score 越大置信度越高
            ttl_seconds=self.signal_ttl,
            reason_code=f"cross_market_dislocation_z{z_score:.2f}",
        )

        await self.event_bus.publish(Topics.SIGNAL_GENERATED, signal)
        logger.info("signal_generated", signal_id=signal.signal_id, market_id=market_id, side=side.value, z_score=z_score)
