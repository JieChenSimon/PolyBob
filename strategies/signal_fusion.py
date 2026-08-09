"""
信号融合策略 - 动态权重多信号整合
"""
from typing import Optional, Dict, List
from dataclasses import dataclass
from datetime import datetime
from modules.strategy_engine.base import Strategy, StrategySignal
from libs.schemas import Side
import math
import numpy as np


@dataclass
class SignalInput:
    """单个信号输入"""
    name: str
    direction: int  # 1=做多, -1=做空, 0=观望
    strength: float  # 0-1
    timestamp: datetime = None


class SignalFusion(Strategy):
    """动态权重信号融合策略

    When ``state_store`` is provided (e.g. ``libs.db.strategy_state.StrategyStateStore``),
    adaptive weights and performance history are loaded on init and persisted
    after every weight update, so live/backtest restarts keep learned state.
    Default (``state_store=None``) keeps the original in-memory behavior.
    """

    def __init__(self, config: dict = None, state_store=None):
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

        # 注入型信号（如 proven_signals 的 tsmom/reversal/xsmom）的默认权重。
        # 这些信号不在自适应学习的基础 5 信号里，给一个静态权重让其参与融合，
        # 同时不污染基础权重的 softmax 学习与持久化。
        self.injected_signal_weight = float(self.config.get('proven_signal_weight', 0.2))

        # 权重学习配置 (grounded in ensemble best practice):
        # - softmax 温度: 越小则权重越集中在近期表现好的信号上 (指数奖励优胜者)。
        # - recency_decay: EWMA 衰减因子 (<1 表示近期表现权重更高)。
        # - weight_floor: 每个信号的权重下限,避免某个信号被完全清零 (过拟合近期)。
        self.weight_temperature = float(self.config.get('weight_temperature', 0.5))
        self.recency_decay = float(self.config.get('recency_decay', 0.94))
        self.weight_floor = float(self.config.get('weight_floor', 0.02))

        # 可选持久化：恢复上次学习到的权重/表现
        self.state_store = state_store
        if self.state_store is not None:
            self.load_state()

    def load_state(self) -> bool:
        """Restore weights/performance_history from the state store.

        Corrupt or missing state degrades to the built-in defaults.
        Returns True when persisted state was applied.
        """
        if self.state_store is None:
            return False
        try:
            state = self.state_store.load_state(self.strategy_id)
        except Exception:
            return False
        weights = state.get('weights')
        history = state.get('performance_history')
        if not isinstance(weights, dict) or not isinstance(history, dict):
            return False
        # Only accept known signal names with numeric values; anything else
        # is treated as corrupt and ignored (unknown != safe).
        if set(weights) != set(self.weights):
            return False
        try:
            restored_weights = {k: float(v) for k, v in weights.items()}
        except (TypeError, ValueError):
            return False
        restored_history = {}
        for name in self.weights:
            values = history.get(name, [])
            if not isinstance(values, list):
                return False
            try:
                restored_history[name] = [float(v) for v in values][-self.max_history:]
            except (TypeError, ValueError):
                return False
        self.weights = restored_weights
        self.performance_history = restored_history
        return True

    def save_state(self) -> None:
        """Persist current weights/performance_history (no-op without store)."""
        if self.state_store is None:
            return
        try:
            self.state_store.save_state(
                self.strategy_id,
                {
                    'weights': self.weights,
                    'performance_history': self.performance_history,
                },
            )
        except Exception:
            # Persistence must never break signal generation.
            pass

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

        # 6. 已被验证的系统性信号（可选注入，向后兼容）。
        # 上游按因果方式（仅用历史）从价格序列计算好这些 [-1,1] 的分值后，
        # 作为特征注入，即可让时序动量 / 短期反转 / 截面动量等经典策略
        # 参与融合（详见 strategies/proven_signals.py）。
        for feature_key, signal_name in (
            ('tsmom_signal', 'tsmom'),
            ('reversal_signal', 'reversal'),
            ('xsmom_signal', 'xsmom'),
        ):
            if feature_key in features and features[feature_key] is not None:
                score = max(-1.0, min(1.0, float(features[feature_key])))
                direction = 1 if score > 0 else -1 if score < 0 else 0
                signals[signal_name] = SignalInput(signal_name, direction, abs(score))

        return signals

    def _recency_weighted_mean(self, history: List[float]) -> float:
        """EWMA over a signal's win/loss history (recent outcomes weighted more).

        Empty history falls back to the neutral prior 0.5. ``recency_decay==1``
        recovers a plain mean.
        """
        if not history:
            return 0.5
        decay = self.recency_decay
        # history is oldest->newest; most recent gets weight 1, older decay^k.
        num = 0.0
        den = 0.0
        w = 1.0
        for value in reversed(history):
            num += w * value
            den += w
            w *= decay
        return num / den if den > 0 else 0.5

    def _update_weights(self, signal_name: str, performance: float):
        """根据历史表现更新权重 (softmax over recency-weighted performance)。

        Linear normalization of average performance rewards signals only
        proportionally; a softmax exponentially rewards the better performers
        (the standard ensemble weighting) while a small floor keeps every signal
        alive so a temporary slump can't permanently zero it out. Weights stay
        normalized to sum to 1, preserving the contract downstream feedback code
        relies on.
        """
        self.performance_history[signal_name].append(performance)
        if len(self.performance_history[signal_name]) > self.max_history:
            self.performance_history[signal_name].pop(0)

        # Recency-weighted average performance per signal.
        scores = {
            name: self._recency_weighted_mean(history)
            for name, history in self.performance_history.items()
        }

        # Softmax over scores (temperature-scaled). Subtract max for numerical
        # stability; guard a degenerate temperature.
        temp = self.weight_temperature if self.weight_temperature > 1e-6 else 1e-6
        max_score = max(scores.values())
        exp_scores = {k: math.exp((v - max_score) / temp) for k, v in scores.items()}
        total = sum(exp_scores.values())
        if total <= 0:
            return
        softmax = {k: v / total for k, v in exp_scores.items()}

        # Guarantee a per-signal floor by mixing the softmax with a uniform
        # distribution: w = (1 - n*floor)*softmax + floor. This keeps the sum
        # at exactly 1 while ensuring every weight >= floor (a plain max()+
        # renormalize would push floored entries back below the floor).
        n = len(softmax)
        floor = max(0.0, min(self.weight_floor, 1.0 / (n + 1)))
        mix = 1.0 - n * floor
        self.weights = {k: mix * v + floor for k, v in softmax.items()}

        # 每次权重更新后持久化（SQLite WAL，成本可忽略）
        self.save_state()

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
            weight = self.weights.get(name, self.injected_signal_weight)
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
        # ``Side`` 只有 BUY_YES/BUY_NO/SELL_YES/SELL_NO —— 没有裸的 BUY/SELL。
        # 方向为正=看涨该结果=BUY_YES；为负=看跌=SELL_YES（与
        # cross_market_dislocation_v1 的多空约定一致）。此前用 Side.BUY/Side.SELL
        # 会在任何方向性信号上抛 AttributeError，令 strategy_engine 实盘路径崩溃。
        return StrategySignal(
            market_id=features.get('market_id', 'unknown'),
            side=Side.BUY_YES if direction > 0 else Side.SELL_YES,
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
