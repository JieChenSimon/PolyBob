"""RL优化器适配器 - 兼容现有StrategyOptimizer接口"""
import logging
import numpy as np
from typing import List, Dict
from datetime import datetime
from pathlib import Path

from services.rl_optimizer.agent import RLAgent
from services.rl_optimizer.environment import TradingEnvironment

logger = logging.getLogger(__name__)


class RLStrategyOptimizer:
    """基于强化学习的策略优化器"""

    def __init__(self, window_size: int = 20, model_path: str = None):
        self.window_size = window_size
        self.param_history = []

        # 当前参数（与原optimizer兼容）
        self.alpha = 0.5
        self.min_confidence = 0.6
        self.stop_loss_pct = 0.02
        self.take_profit_pct = 0.05

        # RL智能体
        state_dim = 6  # 市场状态维度
        action_dim = 9  # 参数调整动作空间
        self.agent = RLAgent(state_dim, action_dim, epsilon=0.1)

        # 加载模型
        if model_path and Path(model_path).exists():
            self._load_model(model_path)
            logger.info(f"已加载RL模型: {model_path}")

        self.training_mode = True
        self.update_count = 0

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
        """使用RL智能体优化参数"""
        if len(trades) < self.window_size:
            return False

        metrics = self.calculate_metrics(trades)
        old_params = self._get_current_params()

        # 构建状态
        state = self._build_state(metrics, trades[-self.window_size:])

        # RL智能体选择动作
        action = self.agent.select_action(state, training=self.training_mode)

        # 应用动作调整参数
        self._apply_action(action)

        # 计算奖励
        reward = metrics["sharpe"] + metrics["win_rate"] - 0.5

        # 存储经验并更新
        if self.training_mode:
            next_state = self._build_state(metrics, trades[-self.window_size:])
            self.agent.store_transition(state, action, reward, next_state, False)

            loss = self.agent.update()
            if loss is not None:
                self.update_count += 1
                if self.update_count % 10 == 0:
                    logger.info(f"RL更新 #{self.update_count}, loss={loss:.4f}")

        new_params = self._get_current_params()
        if old_params != new_params:
            self._record_change(metrics, old_params, new_params)
            return True
        return False

    def _build_state(self, metrics: Dict, recent_trades: List[Dict]) -> np.ndarray:
        """构建RL状态向量"""
        return np.array([
            metrics["win_rate"],
            metrics["avg_return"],
            metrics["sharpe"],
            self.alpha,
            self.min_confidence,
            self.stop_loss_pct
        ], dtype=np.float32)

    def _apply_action(self, action: int):
        """应用RL动作调整参数"""
        # 动作映射: 0-2调整alpha, 3-5调整confidence, 6-8调整止损
        if action < 3:
            delta = (action - 1) * 0.05  # -0.05, 0, +0.05
            self.alpha = np.clip(self.alpha + delta, 0.3, 0.7)
        elif action < 6:
            delta = (action - 4) * 0.05
            self.min_confidence = np.clip(self.min_confidence + delta, 0.5, 0.75)
        else:
            delta = (action - 7) * 0.005
            self.stop_loss_pct = np.clip(self.stop_loss_pct + delta, 0.015, 0.03)

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
        logger.info(f"RL优化: 胜率={metrics['win_rate']:.2%}, 夏普={metrics['sharpe']:.2f}")

    def get_params(self) -> Dict:
        """获取当前优化参数"""
        return self._get_current_params()

    def get_history(self) -> List[Dict]:
        """获取参数变化历史"""
        return self.param_history

    def set_training_mode(self, enabled: bool):
        """设置训练模式"""
        self.training_mode = enabled
        logger.info(f"RL训练模式: {'开启' if enabled else '关闭'}")

    def save_model(self, path: str):
        """保存RL模型"""
        import torch
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        torch.save({
            'policy_net': self.agent.policy_net.state_dict(),
            'target_net': self.agent.target_net.state_dict(),
            'optimizer': self.agent.optimizer.state_dict(),
            'epsilon': self.agent.epsilon
        }, path)
        logger.info(f"RL模型已保存: {path}")

    def _load_model(self, path: str):
        """加载RL模型"""
        import torch
        checkpoint = torch.load(path, map_location=self.agent.device)
        self.agent.policy_net.load_state_dict(checkpoint['policy_net'])
        self.agent.target_net.load_state_dict(checkpoint['target_net'])
        self.agent.optimizer.load_state_dict(checkpoint['optimizer'])
        self.agent.epsilon = checkpoint['epsilon']

    def get_training_stats(self) -> Dict:
        """获取训练统计"""
        return {
            "update_count": self.update_count,
            "epsilon": self.agent.epsilon,
            "buffer_size": len(self.agent.replay_buffer),
            "training_mode": self.training_mode
        }
