"""加密货币交易所客户端基类"""
from abc import ABC, abstractmethod
from typing import Dict, Optional

class CryptoExchangeClient(ABC):
    """交易所客户端抽象基类"""

    @abstractmethod
    def get_ticker(self, symbol: str) -> Optional[Dict]:
        """获取行情"""
        pass

    @abstractmethod
    def get_orderbook(self, symbol: str) -> Optional[Dict]:
        """获取订单簿"""
        pass

    @abstractmethod
    def place_order(
        self,
        symbol: str,
        side: str,
        price: float,
        size: float,
        order_type: str = "LIMIT",
    ) -> str:
        """下单"""
        pass

    @abstractmethod
    def cancel_order(self, order_id: str, symbol: str | None = None) -> bool:
        """撤单"""
        pass

    @abstractmethod
    def get_position(self, symbol: str) -> Optional[Dict]:
        """获取持仓"""
        pass

    @abstractmethod
    def get_order(self, order_id: str, symbol: str | None = None) -> Optional[Dict]:
        """查询订单"""
        pass
