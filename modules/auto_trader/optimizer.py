"""策略优化器 - 基于交易表现动态调整参数"""
import logging
from typing import List, Dict, Optional
from datetime import datetime
import numpy as np

logger = logging.getLogger(__name__)


class StrategyOptimizer:
    """策略参数自适应优化器"""

    def __init__(self, window_size: int = 20):
        self.window_size = window_size  # 滑动窗口大小
        self.param_history = []  # 参数变化历史

        # 当前参数
        self.alpha = 0.5  # AI权重
        self.min_confidence = 0.6  # 置信度阈值
        self.stop_loss_pct = 0.02  # 止损比例
        self.take_profit_pct = 0.05  # 止盈比例

        # 参数调整范围
        self.alpha_range = (0.3, 0.7)
        self.confidence_range = (0.5, 0.75)
        self.stop_loss_range = (0.015, 0.03)
        self.take_profit_range = (0.03, 0.08)

        # 调整步长
        self.alpha_step = 0.05
        self.confidence_step = 0.05
        self.stop_step = 0.005
        self.profit_step = 0.01

    def calculate_metrics(self, trades: List[Dict]) -> Dict:
        """计算交易指标"""
        if not trades:
            return {"win_rate": 0.5, "avg_return": 0, "sharpe": 0}

        recent = trades[-self.window_size:]
        wins = [t for t in recent if t["pnl"] > 0]
        win_rate = len(wins) / len(recent)

        returns = [t["pnl_pct"] / 100 for t in recent]
        avg_return = np.mean(returns)
        sharpe = avg_return / np.std(returns) if np.std(returns) > 0 else 0

        return {"win_rate": win_rate, "avg_return": avg_return, "sharpe": sharpe}

    def optimize(self, trades: List[Dict]) -> bool:
        """基于交易表现优化参数"""
        if len(trades) < self.window_size:
            return False

        metrics = self.calculate_metrics(trades)
        old_params = self._get_current_params()

        # 调整AI权重
        if metrics["sharpe"] < 0.5:
            self.alpha = max(self.alpha_range[0], self.alpha - self.alpha_step)
        elif metrics["sharpe"] > 1.5:
            self.alpha = min(self.alpha_range[1], self.alpha + self.alpha_step)

        # 调整置信度阈值
        if metrics["win_rate"] < 0.45:
            self.min_confidence = min(self.confidence_range[1], self.min_confidence + self.confidence_step)
        elif metrics["win_rate"] > 0.65:
            self.min_confidence = max(self.confidence_range[0], self.min_confidence - self.confidence_step)

        # 调整止损止盈
        if metrics["avg_return"] < -0.01:
            self.stop_loss_pct = max(self.stop_loss_range[0], self.stop_loss_pct - self.stop_step)
        elif metrics["avg_return"] > 0.02:
            self.take_profit_pct = min(self.take_profit_range[1], self.take_profit_pct + self.profit_step)

        new_params = self._get_current_params()
        if old_params != new_params:
            self._record_change(metrics, old_params, new_params)
            return True
        return False

    def _get_current_params(self) -> Dict:
        """获取当前参数"""
        return {
            "alpha": self.alpha,
            "min_confidence": self.min_confidence,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct
        }

    def _record_change(self, metrics: Dict, old: Dict, new: Dict):
        """记录参数变化"""
        record = {
            "timestamp": datetime.now(),
            "metrics": metrics,
            "old_params": old,
            "new_params": new
        }
        self.param_history.append(record)
        logger.info(f"参数优化: 胜率={metrics['win_rate']:.2%}, 夏普={metrics['sharpe']:.2f}")
        logger.info(f"  alpha: {old['alpha']:.2f} -> {new['alpha']:.2f}")
        logger.info(f"  置信度: {old['min_confidence']:.2f} -> {new['min_confidence']:.2f}")

    def get_params(self) -> Dict:
        """获取当前优化参数"""
        return self._get_current_params()

    def get_history(self) -> List[Dict]:
        """获取参数变化历史"""
        return self.param_history
