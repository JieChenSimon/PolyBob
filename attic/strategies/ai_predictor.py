"""
AI Predictor - 智能预测模块
分析市场情绪和技术形态，生成交易信号
"""
from typing import Dict, Any, List
from datetime import datetime


class AIPredictor:
    """AI预测器 - 基于情绪和技术分析生成信号"""

    def __init__(self):
        # 看涨关键词
        self.bullish_keywords = [
            'surge', 'rally', 'bullish', 'optimistic', 'positive',
            'growth', 'increase', 'rise', 'up', 'gain', 'win',
            '上涨', '看涨', '乐观', '增长', '利好'
        ]
        # 看跌关键词
        self.bearish_keywords = [
            'crash', 'drop', 'bearish', 'pessimistic', 'negative',
            'decline', 'decrease', 'fall', 'down', 'loss', 'lose',
            '下跌', '看跌', '悲观', '下降', '利空'
        ]

    def analyze_sentiment(self, news: List[str], social_media: List[str]) -> Dict[str, Any]:
        """分析市场情绪"""
        all_text = ' '.join(news + social_media).lower()

        bullish_count = sum(1 for kw in self.bullish_keywords if kw in all_text)
        bearish_count = sum(1 for kw in self.bearish_keywords if kw in all_text)
        total = bullish_count + bearish_count

        if total == 0:
            return {'signal': 'neutral', 'score': 0.5}

        bullish_ratio = bullish_count / total
        if bullish_ratio > 0.6:
            return {'signal': 'bullish', 'score': bullish_ratio}
        elif bullish_ratio < 0.4:
            return {'signal': 'bearish', 'score': 1 - bullish_ratio}
        return {'signal': 'neutral', 'score': 0.5}

    def analyze_technical(self, prices: List[float]) -> Dict[str, Any]:
        """分析技术形态"""
        if len(prices) < 3:
            return {'signal': 'neutral', 'score': 0.5}

        recent = prices[-3:]
        trend = (recent[-1] - recent[0]) / recent[0] if recent[0] != 0 else 0

        if trend > 0.02:
            return {'signal': 'bullish', 'score': min(0.5 + trend * 10, 0.9)}
        elif trend < -0.02:
            return {'signal': 'bearish', 'score': min(0.5 - trend * 10, 0.9)}
        return {'signal': 'neutral', 'score': 0.5}

    def predict(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """生成AI预测信号"""
        news = market_data.get('news', [])
        social = market_data.get('social_media', [])
        prices = market_data.get('prices', [])

        sentiment = self.analyze_sentiment(news, social)
        technical = self.analyze_technical(prices)

        # 综合评分
        combined_score = (sentiment['score'] * 0.6 + technical['score'] * 0.4)

        # 确定信号
        if combined_score > 0.6:
            signal = 'long'
            confidence = combined_score
            reason = f"情绪{sentiment['signal']}({sentiment['score']:.2f}), 技术{technical['signal']}({technical['score']:.2f})"
        elif combined_score < 0.4:
            signal = 'short'
            confidence = 1 - combined_score
            reason = f"情绪{sentiment['signal']}({sentiment['score']:.2f}), 技术{technical['signal']}({technical['score']:.2f})"
        else:
            signal = 'neutral'
            confidence = 0.5
            reason = "市场信号不明确"

        return {
            'signal': signal,
            'confidence': round(confidence, 2),
            'reason': reason,
            'timestamp': datetime.now().isoformat()
        }
