"""
混合策略 - 传统量化 + AI信号融合
"""
from typing import Optional, List
from services.strategy_engine.base import Strategy, StrategySignal
from libs.quant.signal_fusion import SignalEnsemble


class HybridStrategy(Strategy):
    """混合策略 - 融合多个量化策略和AI信号"""

    def __init__(self, quant_strategies: List[Strategy], ai_strategy: Strategy, config: dict = None):
        super().__init__("hybrid", config)
        self.quant_strategies = quant_strategies
        self.ai_strategy = ai_strategy
        self.ensemble = SignalEnsemble(alpha=self.config.get("alpha", 0.5))
        self.min_confidence = self.config.get("min_confidence", 0.65)

    async def generate_signal(self, features: dict) -> Optional[StrategySignal]:
        """生成融合信号"""
        # 收集量化信号
        quant_signals = []
        for strategy in self.quant_strategies:
            signal = await strategy.generate_signal(features)
            if signal:
                quant_signals.append(signal)

        # 收集AI信号
        ai_signal = await self.ai_strategy.generate_signal(features)

        # 融合
        final_signal = self.ensemble.combine_signals(quant_signals, ai_signal)

        if final_signal and final_signal.confidence >= self.min_confidence:
            return final_signal

        return None

    def update_performance(self, quant_return: float, ai_return: float):
        """更新策略表现，动态调整权重"""
        self.ensemble.update_weights(quant_return, ai_return)
