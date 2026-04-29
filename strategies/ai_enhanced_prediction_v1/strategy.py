"""
AI Enhanced Prediction Strategy V1 - AI 增强预测策略

核心逻辑:
- 使用 Claude API 分析市场特征和问题文本
- 生成结构化的交易信号和置信度评估
- 结合量化特征和 AI 推理
"""
import asyncio
import structlog
from datetime import datetime
from typing import Dict, Optional
import uuid
import json

from libs.events import get_event_bus, Topics
from libs.schemas import Signal, Side
from libs.config import get_settings

logger = structlog.get_logger()


class AIEnhancedPredictionV1:
    """AI 增强预测策略"""

    def __init__(self, config: dict):
        self.strategy_id = "ai_enhanced_prediction_v1"
        self.event_bus = get_event_bus()
        self.settings = get_settings()

        # 配置参数
        self.min_confidence = config.get("min_confidence", 0.6)
        self.signal_ttl = config.get("signal_ttl_seconds", 600)
        self.analysis_interval = config.get("analysis_interval_seconds", 60)

        # 市场特征缓存
        self.features: Dict[str, dict] = {}
        self.market_info: Dict[str, dict] = {}

        # AI 客户端(延迟初始化)
        self._client: Optional[object] = None
        self._last_analysis: Dict[str, datetime] = {}

        self._running = False

    async def start(self):
        """启动策略"""
        logger.info("starting_strategy", strategy_id=self.strategy_id)
        self._running = True

        # 初始化 AI 客户端
        await self._init_ai_client()

        # 订阅特征快照
        await self.event_bus.subscribe(Topics.FEATURE_SNAPSHOT, self._on_feature_snapshot)
        await self.event_bus.subscribe(Topics.MARKET_DISCOVERED, self._on_market_discovered)

    async def stop(self):
        """停止策略"""
        logger.info("stopping_strategy", strategy_id=self.strategy_id)
        self._running = False

    async def _init_ai_client(self):
        """初始化 AI 客户端"""
        if not self.settings.anthropic_api_key:
            logger.warning("anthropic_api_key_not_set", strategy_id=self.strategy_id)
            return

        try:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=self.settings.anthropic_api_key)
            logger.info("ai_client_initialized", strategy_id=self.strategy_id)
        except ImportError:
            logger.error("anthropic_package_not_installed")
        except Exception as e:
            logger.error("ai_client_init_error", error=str(e))

    async def _on_market_discovered(self, market_data: dict):
        """处理市场发现事件"""
        market_id = market_data.get("market_id")
        if market_id:
            self.market_info[market_id] = market_data

    async def _on_feature_snapshot(self, feature_data: dict):
        """处理特征快照"""
        market_id = feature_data["market_id"]
        self.features[market_id] = feature_data

        # 检查是否需要 AI 分析
        now = datetime.utcnow()
        last_analysis = self._last_analysis.get(market_id)

        if last_analysis and (now - last_analysis).total_seconds() < self.analysis_interval:
            return

        # 执行 AI 分析
        await self._analyze_with_ai(market_id, feature_data)
        self._last_analysis[market_id] = now

    async def _analyze_with_ai(self, market_id: str, features: dict):
        """使用 AI 分析市场"""
        if not self._client:
            return

        market_info = self.market_info.get(market_id, {})
        question = market_info.get("question", "Unknown")

        # 构建 prompt
        prompt = self._build_analysis_prompt(question, features)

        try:
            # 调用 Claude API
            response = await self._client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )

            # 解析响应
            content = response.content[0].text
            analysis = self._parse_ai_response(content)

            if analysis:
                await self._generate_signal_from_analysis(market_id, features, analysis)

        except Exception as e:
            logger.error("ai_analysis_error", market_id=market_id, error=str(e))

    def _build_analysis_prompt(self, question: str, features: dict) -> str:
        """构建分析 prompt"""
        return f"""Analyze this prediction market and provide a trading signal.

Market Question: {question}

Current Market Features:
- Mid Price: {features.get('mid_price', 0):.4f}
- Spread (bps): {features.get('spread_bps', 0):.1f}
- Depth Imbalance: {features.get('depth_imbalance', 0):.3f}
- Trade Intensity (1m): {features.get('trade_intensity_1m', 0)}
- Volume (1m): {features.get('volume_1m', 0):.2f}
- Price Jump Score: {features.get('price_jump_score', 0):.2f}

Provide your analysis in JSON format:
{{
  "signal": "BUY_YES" | "SELL_YES" | "NEUTRAL",
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation",
  "expected_edge_bps": estimated edge in basis points
}}

Focus on:
1. Market inefficiencies based on features
2. Probability assessment of the outcome
3. Risk/reward ratio

Respond with ONLY the JSON object, no additional text."""

    def _parse_ai_response(self, content: str) -> Optional[dict]:
        """解析 AI 响应"""
        try:
            # 提取 JSON
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                json_str = content[start:end]
                return json.loads(json_str)
        except Exception as e:
            logger.error("ai_response_parse_error", error=str(e), content=content[:200])
        return None

    async def _generate_signal_from_analysis(self, market_id: str, features: dict, analysis: dict):
        """从 AI 分析生成信号"""
        signal_type = analysis.get("signal", "NEUTRAL")
        confidence = analysis.get("confidence", 0.0)

        if signal_type == "NEUTRAL" or confidence < self.min_confidence:
            return

        # 映射信号类型
        side_map = {
            "BUY_YES": Side.BUY_YES,
            "SELL_YES": Side.SELL_YES,
        }

        side = side_map.get(signal_type)
        if not side:
            return

        signal = Signal(
            signal_id=str(uuid.uuid4()),
            market_id=market_id,
            strategy_id=self.strategy_id,
            timestamp=datetime.utcnow(),
            side=side,
            price=features["mid_price"],
            size=100.0,
            expected_edge_bps=analysis.get("expected_edge_bps", 0.0),
            confidence=confidence,
            ttl_seconds=self.signal_ttl,
            reason_code=f"ai_prediction_{signal_type.lower()}",
            explanation_ref=analysis.get("reasoning"),
        )

        await self.event_bus.publish(Topics.SIGNAL_GENERATED, signal)
        logger.info(
            "ai_signal_generated",
            signal_id=signal.signal_id,
            market_id=market_id,
            side=side.value,
            confidence=confidence,
        )
