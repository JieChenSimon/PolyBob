"""
信号融合策略 - 动态权重多信号整合
"""
from typing import Optional, Dict, List
from dataclasses import dataclass
from datetime import datetime
from services.strategy_engine.base import Strategy, StrategySignal
from libs.schemas import Side
import numpy as np


@dataclass
class SignalInput:
    """单个信号输入"""
    name: str
    direction: int  # 1=做多, -1=做空, 0=观望
    strength: float  # 0-1
    timestamp: datetime = None


class SignalFusion(Strategy):
    """动态权重信号融合策略"""

    def __init__(self, config: dict = None):
        super().__init__("signal_fusion", config)

        # 初始权重（均等）
        self.weights = {
            'dual_ma': 0.20,
            'rsi': 0.20,
            'macd': 0.20,
            'bollinger': 0.20,
            'ai_predict': 0.20
        }

        # 历史表现追踪
        self.performance_history = {k: [] for k in self.weights.keys()}
        self.max_history = 50

        # 阈值配置
        self.min_confidence = self.config.get('min_confidence', 0.6)
        self.conflict_threshold = self.config.get('conflict_threshold', 0.3)

    def _calculate_signal_scores(self, features: dict) -> Dict[str, SignalInput]:
        """计算各信号得分"""
        signals = {}

        # 1. 双均线信号
        if 'ma_fast' in features and 'ma_slow' in features:
            diff = (features['ma_fast'] - features['ma_slow']) / features['ma_slow']
            direction = 1 if diff > 0 else -1 if diff < 0 else 0
            strength = min(abs(diff) * 10, 1.0)
            signals['dual_ma'] = SignalInput('dual_ma', direction, strength)

        # 2. RSI信号
        if 'rsi' in features:
            rsi = features['rsi']
            if rsi < 30:
                signals['rsi'] = SignalInput('rsi', 1, (30 - rsi) / 30)
            elif rsi > 70:
                signals['rsi'] = SignalInput('rsi', -1, (rsi - 70) / 30)
            else:
                signals['rsi'] = SignalInput('rsi', 0, 0.0)

        # 3. MACD信号
        if 'macd' in features and 'macd_signal' in features:
            diff = features['macd'] - features['macd_signal']
            direction = 1 if diff > 0 else -1 if diff < 0 else 0
            strength = min(abs(diff) * 5, 1.0)
            signals['macd'] = SignalInput('macd', direction, strength)

        # 4. 布林带信号
        if all(k in features for k in ['price', 'bb_upper', 'bb_lower', 'bb_middle']):
            price = features['price']
            bb_width = features['bb_upper'] - features['bb_lower']
            if price < features['bb_lower']:
                signals['bollinger'] = SignalInput('bollinger', 1,
                    (features['bb_lower'] - price) / bb_width)
            elif price > features['bb_upper']:
                signals['bollinger'] = SignalInput('bollinger', -1,
                    (price - features['bb_upper']) / bb_width)
            else:
                signals['bollinger'] = SignalInput('bollinger', 0, 0.0)

        # 5. AI预测信号
        if 'ai_direction' in features and 'ai_confidence' in features:
            signals['ai_predict'] = SignalInput('ai_predict',
                features['ai_direction'], features['ai_confidence'])

        return signals

    def _update_weights(self, signal_name: str, performance: float):
        """根据历史表现更新权重"""
        self.performance_history[signal_name].append(performance)
        if len(self.performance_history[signal_name]) > self.max_history:
            self.performance_history[signal_name].pop(0)

        # 计算平均表现并归一化权重
        avg_perf = {}
        for name, history in self.performance_history.items():
            avg_perf[name] = np.mean(history) if history else 0.5

        total = sum(avg_perf.values())
        if total > 0:
            self.weights = {k: v / total for k, v in avg_perf.items()}

    def _detect_conflict(self, signals: Dict[str, SignalInput]) -> bool:
        """检测信号冲突"""
        directions = [s.direction for s in signals.values() if s.direction != 0]
        if not directions:
            return False

        long_count = sum(1 for d in directions if d > 0)
        short_count = sum(1 for d in directions if d < 0)
        total = len(directions)

        conflict_ratio = min(long_count, short_count) / total
        return conflict_ratio > self.conflict_threshold

    def _fuse_signals(self, signals: Dict[str, SignalInput]) -> tuple:
        """融合信号输出最终决策"""
        if not signals:
            return 0, 0.0, "无有效信号"

        # 检测冲突
        if self._detect_conflict(signals):
            return 0, 0.0, "信号冲突，观望"

        # 加权融合
        weighted_direction = 0.0
        total_weight = 0.0

        for name, signal in signals.items():
            weight = self.weights.get(name, 0.0)
            weighted_direction += signal.direction * signal.strength * weight
            total_weight += weight * signal.strength

        if total_weight == 0:
            return 0, 0.0, "信号强度不足"

        # 归一化
        final_score = weighted_direction / total_weight
        confidence = min(abs(final_score), 1.0)

        # 决策
        if confidence < self.min_confidence:
            return 0, confidence, f"置信度不足 ({confidence:.2f})"

        direction = 1 if final_score > 0 else -1
        action = "做多" if direction > 0 else "做空"

        return direction, confidence, f"{action} (融合{len(signals)}个信号)"

    async def generate_signal(self, features: dict) -> Optional[StrategySignal]:
        """生成融合信号"""
        # 计算各信号
        signals = self._calculate_signal_scores(features)

        # 融合决策
        direction, confidence, reason = self._fuse_signals(signals)

        if direction == 0:
            return None

        # 构造信号
        return StrategySignal(
            market_id=features.get('market_id', 'unknown'),
            side=Side.BUY if direction > 0 else Side.SELL,
            price=features.get('price', 0.0),
            size=features.get('size', 0.0),
            confidence=confidence,
            expected_edge_bps=confidence * 100,
            reason=reason
        )

    def update_performance(self, signal_name: str, actual_return: float):
        """更新信号表现（外部调用）"""
        performance = 1.0 if actual_return > 0 else 0.0
        self._update_weights(signal_name, performance)
