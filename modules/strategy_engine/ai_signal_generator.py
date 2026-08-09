"""
AI Signal Generator - AI 信号生成器

职责:
- 将市场特征转换为 AI prompt
- 调用 LLM 生成交易决策
- 解析 AI 输出为标准信号
"""
from typing import Optional
import json
import structlog

from .base import StrategySignal
from libs.schemas import Side

logger = structlog.get_logger()


class AISignalGenerator:
    """AI 信号生成器"""

    def __init__(self, llm_client=None):
        """
        Args:
            llm_client: LLM 客户端 (如 Anthropic Claude API)
        """
        self.llm_client = llm_client

    async def generate_signal(
        self,
        features: dict,
        market_context: dict = None
    ) -> Optional[StrategySignal]:
        """
        使用 AI 生成交易信号

        Args:
            features: 市场特征
            market_context: 市场上下文(问题描述、类别等)

        Returns:
            StrategySignal 或 None
        """
        if not self.llm_client:
            return None

        # 构建 prompt
        prompt = self._build_prompt(features, market_context)

        try:
            # 调用 LLM
            response = await self._call_llm(prompt)

            # 解析响应
            signal = self._parse_response(response, features)

            return signal

        except Exception as e:
            logger.error("ai_signal_generation_error", error=str(e), exc_info=True)
            return None

    def _build_prompt(self, features: dict, market_context: dict = None) -> str:
        """构建 AI prompt"""
        market_id = features.get("market_id", "unknown")
        question = market_context.get("question", "") if market_context else ""

        prompt = f"""You are a quantitative trading expert analyzing a prediction market.

Market: {market_id}
Question: {question}

Current Market Features:
- Mid Price: {features.get('mid_price', 0):.4f}
- Spread: {features.get('spread_bps', 0):.1f} bps
- Bid: {features.get('bid_price', 0):.4f} (size: {features.get('bid_size', 0):.1f})
- Ask: {features.get('ask_price', 0):.4f} (size: {features.get('ask_size', 0):.1f})
- Depth Imbalance: {features.get('depth_imbalance', 0):.3f}
- Trade Intensity (1m): {features.get('trade_intensity_1m', 0):.0f}
- Volume (1m): {features.get('volume_1m', 0):.1f}
- Price Jump Score: {features.get('price_jump_score', 0):.2f}

Task: Decide if there is a trading opportunity.

Output JSON format:
{{
  "action": "buy_yes" | "sell_yes" | "no_trade",
  "confidence": 0.0-1.0,
  "expected_edge_bps": float,
  "size": float,
  "reasoning": "brief explanation"
}}

Consider:
1. Is the spread wide enough to profit?
2. Does depth imbalance suggest price movement?
3. Is there unusual trading activity?
4. What is the risk/reward ratio?

Respond with JSON only."""

        return prompt

    async def _call_llm(self, prompt: str) -> str:
        """调用 LLM API"""
        # 这里需要实际的 LLM 客户端实现
        # 示例: Anthropic Claude API
        if hasattr(self.llm_client, 'messages'):
            response = await self.llm_client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text
        else:
            raise NotImplementedError("LLM client not configured")

    def _parse_response(
        self,
        response: str,
        features: dict
    ) -> Optional[StrategySignal]:
        """解析 AI 响应"""
        try:
            # 提取 JSON
            response = response.strip()
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                response = response.split("```")[1].split("```")[0]

            data = json.loads(response)

            action = data.get("action")
            if action == "no_trade":
                return None

            # 映射 action 到 Side
            side_map = {
                "buy_yes": Side.BUY_YES,
                "sell_yes": Side.SELL_YES,
                "buy_no": Side.BUY_NO,
                "sell_no": Side.SELL_NO
            }

            side = side_map.get(action)
            if not side:
                return None

            confidence = float(data.get("confidence", 0.5))
            expected_edge_bps = float(data.get("expected_edge_bps", 0))
            size = float(data.get("size", 10.0))
            reasoning = data.get("reasoning", "")

            # 确定价格
            if side in [Side.BUY_YES, Side.BUY_NO]:
                price = features.get("ask_price", features.get("mid_price", 0))
            else:
                price = features.get("bid_price", features.get("mid_price", 0))

            return StrategySignal(
                market_id=features.get("market_id"),
                side=side,
                price=price,
                size=size,
                confidence=confidence,
                expected_edge_bps=expected_edge_bps,
                reason=f"ai:{reasoning[:50]}"
            )

        except Exception as e:
            logger.error("ai_response_parse_error", error=str(e), response=response)
            return None
