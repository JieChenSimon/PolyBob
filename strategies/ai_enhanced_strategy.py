"""
AI Enhanced Strategy - 使用 Strategy 基类的 AI 增强策略
"""
from typing import Optional
from services.strategy_engine.base import Strategy, StrategySignal
from services.strategy_engine.ai_signal_generator import AISignalGenerator
from libs.config import get_settings


class AIEnhancedStrategy(Strategy):
    """AI 增强策略 - 集成 Claude API"""

    def __init__(self, config: dict = None):
        super().__init__("ai_enhanced", config)

        self.min_confidence = self.config.get("min_confidence", 0.6)
        self.ai_generator = None
        self._init_ai_client()

    def _init_ai_client(self):
        """初始化 AI 客户端"""
        settings = get_settings()
        if settings.anthropic_api_key:
            try:
                import anthropic
                client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
                self.ai_generator = AISignalGenerator(llm_client=client)
            except ImportError:
                pass

    async def generate_signal(self, features: dict) -> Optional[StrategySignal]:
        """生成信号"""
        if not self.ai_generator:
            return None

        signal = await self.ai_generator.generate_signal(features)

        if signal and signal.confidence >= self.min_confidence:
            return signal

        return None
