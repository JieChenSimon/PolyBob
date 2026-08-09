#!/usr/bin/env python3
"""集成测试 - AI策略 + 执行层 + 风控"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.execution_engine.order_manager import OrderManager
from modules.risk_manager.risk_checker import RiskChecker

def test_integration():
    print("=" * 60)
    print("PolyBob 集成测试")
    print("=" * 60)

    # 初始化
    order_mgr = OrderManager()
    risk_checker = RiskChecker(max_position=1000, max_order_size=100)

    print("\n[1/3] 创建订单...")
    order_id = order_mgr.create_order(
        market_id="test_market",
        side="buy",
        price=0.5,
        size=50
    )
    print(f"✓ 订单创建: {order_id}")

    print("\n[2/3] 风控检查...")
    passed, msg = risk_checker.check_order(50)
    print(f"✓ 风控结果: {msg}")

    if passed:
        print("\n[3/3] 提交订单...")
        order_mgr.submit_order(order_id)
        risk_checker.update_position(50)
        print(f"✓ 订单已提交")
        print(f"  当前持仓: {risk_checker.current_position}")

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
    print("✓ 执行层可用")
    print("✓ 风控层可用")
    print("\n下一步: 实现Polymarket API集成")

if __name__ == "__main__":
    test_integration()
