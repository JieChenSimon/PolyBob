"""
AI信号融合框架 - 传统量化 + AI混合策略
"""
from typing import Optional, List, Tuple
import numpy as np
from modules.strategy_engine.base import StrategySignal


class SignalEnsemble:
    """信号集成器"""

    def __init__(self, alpha: float = 0.5):
        self.alpha = alpha  # 量化信号权重
        self.performance_history = {'quant': [], 'ai': []}

    def update_weights(self, quant_return: float, ai_return: float, learning_rate: float = 0.01):
        """动态更新权重"""
        self.performance_history['quant'].append(quant_return)
        self.performance_history['ai'].append(ai_return)

        # 基于相对表现调整
        if len(self.performance_history['quant']) > 10:
            quant_sharpe = np.mean(self.performance_history['quant'][-10:]) / (np.std(self.performance_history['quant'][-10:]) + 1e-6)
            ai_sharpe = np.mean(self.performance_history['ai'][-10:]) / (np.std(self.performance_history['ai'][-10:]) + 1e-6)

            # 调整alpha
            self.alpha += learning_rate * (quant_sharpe - ai_sharpe)
            self.alpha = np.clip(self.alpha, 0.3, 0.7)

    def combine_signals(
        self,
        quant_signals: List[Optional[StrategySignal]],
        ai_signal: Optional[StrategySignal]
    ) -> Optional[StrategySignal]:
        """融合多个信号"""
        valid_quant = [s for s in quant_signals if s is not None]

        if not valid_quant and not ai_signal:
            return None

        # 量化信号加权平均
        if valid_quant:
            quant_confidence = np.mean([s.confidence for s in valid_quant])
            quant_edge = np.mean([s.expected_edge_bps for s in valid_quant])
            quant_side = valid_quant[0].side
        else:
            quant_confidence = 0.5
            quant_edge = 0.0
            quant_side = None

        # AI信号
        if ai_signal:
            ai_confidence = ai_signal.confidence
            ai_edge = ai_signal.expected_edge_bps
            ai_side = ai_signal.side
        else:
            ai_confidence = 0.5
            ai_edge = 0.0
            ai_side = None

        # 融合
        final_confidence = self.alpha * quant_confidence + (1 - self.alpha) * ai_confidence
        final_edge = self.alpha * quant_edge + (1 - self.alpha) * ai_edge

        # 方向一致性检查
        if quant_side and ai_side and quant_side != ai_side:
            final_confidence *= 0.7  # 降低置信度

        final_side = quant_side if quant_side else ai_side

        if not final_side or final_confidence < 0.6:
            return None

        base_signal = valid_quant[0] if valid_quant else ai_signal
        return StrategySignal(
            market_id=base_signal.market_id,
            side=final_side,
            price=base_signal.price,
            size=base_signal.size,
            confidence=final_confidence,
            expected_edge_bps=final_edge,
            reason=f"ensemble:α={self.alpha:.2f},quant={len(valid_quant)},ai={1 if ai_signal else 0}"
        )


def calibrate_confidence(
    predicted_confidence: float,
    historical_outcomes: List[Tuple[float, bool]]
) -> float:
    """
    Platt Scaling置信度校准

    基于历史(confidence, outcome)数据校准
    """
    if len(historical_outcomes) < 10:
        return predicted_confidence

    confidences = np.array([c for c, _ in historical_outcomes])
    outcomes = np.array([1 if o else 0 for _, o in historical_outcomes])

    # 简化的逻辑回归校准
    bins = np.linspace(0, 1, 11)
    calibrated = predicted_confidence

    for i in range(len(bins) - 1):
        mask = (confidences >= bins[i]) & (confidences < bins[i+1])
        if mask.sum() > 0:
            actual_prob = outcomes[mask].mean()
            if bins[i] <= predicted_confidence < bins[i+1]:
                calibrated = actual_prob
                break

    return calibrated
