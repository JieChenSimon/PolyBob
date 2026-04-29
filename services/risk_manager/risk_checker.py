"""基础风控检查"""

class RiskChecker:
    def __init__(self, max_position=1000, max_order_size=100):
        self.max_position = max_position
        self.max_order_size = max_order_size
        self.current_position = 0

    def check_order(self, size):
        """检查订单是否通过风控"""
        # 检查订单大小
        if size > self.max_order_size:
            return False, "订单超过最大限制"

        # 检查持仓限制
        if abs(self.current_position + size) > self.max_position:
            return False, "持仓超过限制"

        return True, "通过"

    def update_position(self, size):
        """更新持仓"""
        self.current_position += size
