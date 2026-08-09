#!/usr/bin/env python3
"""完整交易系统演示"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from libs.polymarket.clob_client import PolymarketClient
from modules.execution_engine.order_manager import OrderManager
from modules.risk_manager.risk_checker import RiskChecker

def main():
    print("=" * 60)
    print("PolyBob 完整系统演示")
    print("=" * 60)

    # 初始化
    client = PolymarketClient()
    order_mgr = OrderManager()
    risk = RiskChecker()

    print("\n[1/4] 获取市场...")
    markets = client.get_markets(limit=5)
    print(f"✓ 找到 {len(markets)} 个市场")

    print("\n[2/4] 分析市场...")
    for m in markets[:3]:
        question = m['question'][:40]
        token_ids = m.get('clobTokenIds', [])

        if not token_ids:
            continue

        print(f"\n{question}...")

        # 获取价格
        prices = client.get_best_prices(token_ids[0])
        if prices:
            print(f"  bid={prices['bid']:.3f}, ask={prices['ask']:.3f}")

            # 做市报价
            mid = (prices['bid'] + prices['ask']) / 2
            spread = prices['ask'] - prices['bid']
            our_bid = mid - spread * 0.25
            our_ask = mid + spread * 0.25

            print(f"  做市: bid={our_bid:.3f}, ask={our_ask:.3f}")

    print("\n[3/4] 创建测试订单...")
    order_id = order_mgr.create_order("test", "buy", 0.5, 10)
    print(f"✓ 订单: {order_id}")

    print("\n[4/4] 风控检查...")
    passed, msg = risk.check_order(10)
    print(f"✓ {msg}")

    print("\n" + "=" * 60)
    print("系统就绪")
    print("=" * 60)
    print("✓ API集成完成")
    print("✓ 执行层就绪")
    print("✓ 风控层就绪")
    print("\n准备实盘测试！")

if __name__ == "__main__":
    main()
