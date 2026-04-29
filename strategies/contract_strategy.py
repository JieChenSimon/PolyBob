"""合约交易策略 - 数学模型 + AI信号融合"""
import numpy as np
from typing import Dict, Optional

class ContractTradingStrategy:
    """合约交易策略"""

    def __init__(self):
        self.lookback = 20
        self.volatility_threshold = 0.02

    def calculate_technical_indicators(self, prices: np.ndarray) -> Dict:
        """计算技术指标"""
        if len(prices) < self.lookback:
            return {}

        # 移动平均
        sma_short = np.mean(prices[-5:])
        sma_long = np.mean(prices[-20:])

        # 波动率
        returns = np.diff(prices) / prices[:-1]
        volatility = np.std(returns)

        # RSI
        gains = np.maximum(np.diff(prices), 0)
        losses = np.maximum(-np.diff(prices), 0)
        avg_gain = np.mean(gains[-14:]) if len(gains) >= 14 else 0
        avg_loss = np.mean(losses[-14:]) if len(losses) >= 14 else 0
        rs = avg_gain / avg_loss if avg_loss > 0 else 0
        rsi = 100 - (100 / (1 + rs))

        return {
            'sma_short': sma_short,
            'sma_long': sma_long,
            'volatility': volatility,
            'rsi': rsi,
            'trend': 'up' if sma_short > sma_long else 'down'
        }

    def generate_math_signal(self, indicators: Dict) -> Dict:
        """基于数学模型生成信号"""
        if not indicators:
            return {'signal': 'neutral', 'confidence': 0}

        # 趋势信号
        trend_signal = 1 if indicators['trend'] == 'up' else -1

        # RSI超买超卖
        rsi = indicators['rsi']
        rsi_signal = -1 if rsi > 70 else (1 if rsi < 30 else 0)

        # 综合信号
        combined = trend_signal + rsi_signal

        if combined >= 1:
            return {'signal': 'long', 'confidence': 0.6}
        elif combined <= -1:
            return {'signal': 'short', 'confidence': 0.6}
        return {'signal': 'neutral', 'confidence': 0.3}

    def generate_ai_signal(self, news: str, sentiment: str) -> Dict:
        """基于AI分析生成信号"""
        # 简化版：基于关键词
        bullish_words = ['bullish', 'positive', 'upgrade', 'rally']
        bearish_words = ['bearish', 'negative', 'downgrade', 'crash']

        text = (news + " " + sentiment).lower()

        if any(w in text for w in bullish_words):
            return {'signal': 'long', 'confidence': 0.7}
        elif any(w in text for w in bearish_words):
            return {'signal': 'short', 'confidence': 0.7}
        return {'signal': 'neutral', 'confidence': 0.3}

    def fuse_signals(self, math_signal: Dict, ai_signal: Dict, alpha=0.6) -> Dict:
        """融合数学模型和AI信号"""
        # alpha: 数学模型权重，1-alpha: AI权重
        signal_map = {'long': 1, 'short': -1, 'neutral': 0}

        math_score = signal_map[math_signal['signal']] * math_signal['confidence']
        ai_score = signal_map[ai_signal['signal']] * ai_signal['confidence']

        final_score = alpha * math_score + (1 - alpha) * ai_score

        if final_score > 0.4:
            return {'signal': 'long', 'confidence': abs(final_score)}
        elif final_score < -0.4:
            return {'signal': 'short', 'confidence': abs(final_score)}
        return {'signal': 'neutral', 'confidence': 0}
