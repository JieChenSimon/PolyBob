"""RL训练环境 - 市场模拟与交互"""
import numpy as np
from typing import Dict, Tuple, Optional, Any
from dataclasses import dataclass


@dataclass
class MarketState:
    """市场状态"""
    price: float
    volume: float
    volatility: float
    trend: float
    position: float  # -1到1之间
    pnl: float
    timestamp: int


class TradingEnvironment:
    """交易环境 - 符合Gym接口"""

    def __init__(
        self,
        historical_data: Optional[np.ndarray] = None,
        initial_balance: float = 10000.0,
        max_position: float = 1.0,
        transaction_cost: float = 0.001
    ):
        self.historical_data = historical_data
        self.initial_balance = initial_balance
        self.max_position = max_position
        self.transaction_cost = transaction_cost

        # 状态空间维度
        self.observation_space_dim = 6  # price, volume, volatility, trend, position, pnl
        self.action_space_dim = 3  # buy, hold, sell

        self.reset()

    def reset(self) -> np.ndarray:
        """重置环境"""
        self.current_step = 0
        self.balance = self.initial_balance
        self.position = 0.0
        self.entry_price = 0.0
        self.total_pnl = 0.0

        if self.historical_data is not None and len(self.historical_data) > 0:
            self.data = self.historical_data
        else:
            # 生成模拟数据
            self.data = self._generate_synthetic_data(1000)

        return self._get_observation()

    def step(self, action: int) -> Tuple[np.ndarray, float, bool, Dict]:
        """执行动作"""
        if self.current_step >= len(self.data) - 1:
            return self._get_observation(), 0.0, True, {}

        current_price = self.data[self.current_step, 0]

        # 执行动作: 0=sell, 1=hold, 2=buy
        old_position = self.position
        if action == 2:  # buy
            self.position = min(self.position + 0.5, self.max_position)
        elif action == 0:  # sell
            self.position = max(self.position - 0.5, -self.max_position)

        # 计算交易成本
        position_change = abs(self.position - old_position)
        cost = position_change * current_price * self.transaction_cost

        # 更新到下一步
        self.current_step += 1
        next_price = self.data[self.current_step, 0]

        # 计算收益
        price_change = next_price - current_price
        step_pnl = self.position * price_change - cost
        self.total_pnl += step_pnl

        reward = self._calculate_reward(step_pnl, self.position)
        done = self.current_step >= len(self.data) - 1

        return self._get_observation(), reward, done, {'pnl': self.total_pnl}

    def _get_observation(self) -> np.ndarray:
        """获取当前状态观察"""
        if self.current_step >= len(self.data):
            return np.zeros(self.observation_space_dim)

        current = self.data[self.current_step]
        price = current[0]
        volume = current[1] if len(current) > 1 else 0

        # 计算技术指标
        lookback = min(20, self.current_step)
        if lookback > 0:
            prices = self.data[self.current_step - lookback:self.current_step + 1, 0]
            volatility = np.std(prices) if len(prices) > 1 else 0
            trend = (prices[-1] - prices[0]) / prices[0] if prices[0] > 0 else 0
        else:
            volatility = 0
            trend = 0

        return np.array([
            price / 100.0,  # 归一化
            volume / 1000.0,
            volatility,
            trend,
            self.position,
            self.total_pnl / self.initial_balance
        ], dtype=np.float32)

    def _calculate_reward(self, step_pnl: float, position: float) -> float:
        """计算奖励"""
        # 基础收益奖励
        reward = step_pnl / self.initial_balance * 100

        # 惩罚过度持仓
        position_penalty = -0.01 * abs(position) if abs(position) > 0.8 else 0

        return reward + position_penalty

    def _generate_synthetic_data(self, n_steps: int) -> np.ndarray:
        """生成模拟市场数据"""
        np.random.seed(42)

        # 生成价格序列（几何布朗运动）
        mu = 0.0001  # 漂移
        sigma = 0.02  # 波动率
        dt = 1

        prices = [50.0]
        for _ in range(n_steps - 1):
            dW = np.random.normal(0, np.sqrt(dt))
            price = prices[-1] * np.exp((mu - 0.5 * sigma**2) * dt + sigma * dW)
            prices.append(max(price, 1.0))  # 防止负价格

        # 生成成交量
        volumes = np.random.lognormal(6, 1, n_steps)

        return np.column_stack([prices, volumes])

    def render(self) -> str:
        """渲染当前状态"""
        if self.current_step >= len(self.data):
            return "Episode ended"

        price = self.data[self.current_step, 0]
        return (
            f"Step: {self.current_step}, "
            f"Price: {price:.2f}, "
            f"Position: {self.position:.2f}, "
            f"PnL: {self.total_pnl:.2f}"
        )


class RealtimeEnvironment(TradingEnvironment):
    """实时数据环境"""

    def __init__(self, data_buffer_size: int = 1000, **kwargs):
        super().__init__(**kwargs)
        self.data_buffer_size = data_buffer_size
        self.realtime_buffer = []

    def update_realtime_data(self, price: float, volume: float):
        """更新实时数据"""
        self.realtime_buffer.append([price, volume])
        if len(self.realtime_buffer) > self.data_buffer_size:
            self.realtime_buffer.pop(0)

        # 更新环境数据
        if len(self.realtime_buffer) > 0:
            self.data = np.array(self.realtime_buffer)

    def is_ready(self) -> bool:
        """检查是否有足够数据"""
        return len(self.realtime_buffer) >= 20
