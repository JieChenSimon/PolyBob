"""
Strategy Base Classes - 策略基类
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from libs.schemas import Side


@dataclass
class StrategySignal:
    """策略信号输出"""
    market_id: str
    side: Side
    price: float
    size: float
    confidence: float  # 0-1
    expected_edge_bps: float
    reason: str
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


class Strategy(ABC):
    """策略基类"""

    def __init__(self, strategy_id: str, config: dict = None):
        self.strategy_id = strategy_id
        self.config = config or {}
        self.enabled = True

    @abstractmethod
    async def generate_signal(self, features: dict) -> Optional[StrategySignal]:
        """
        生成交易信号

        Args:
            features: 市场特征字典

        Returns:
            StrategySignal 或 None
        """
        pass

    def get_name(self) -> str:
        """获取策略名称"""
        return self.__class__.__name__
