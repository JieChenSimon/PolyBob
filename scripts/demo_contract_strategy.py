#!/usr/bin/env python3
"""合约交易策略演示 - 数学模型 + AI融合"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
from strategies.contract_strategy import ContractTradingStrategy

def demo_contract_strategy():
    print("=" * 60)
    print("合约交易策略演示 - 数学模型 + AI融合")
    print("=" * 60)

    strategy = ContractTradingStrategy()

    # 模拟价格数据
    np.random.seed(42)
    base_price = 70000
    prices = base_price + np.cumsum(np.random.randn(30) * 500)

    print(f"\n当前价格: ${prices[-1]:,.2f}")

    # 计算技术指标
    print("\n[1/3] 计算技术指标...")
    indicators = strategy.calculate_technical_indicators(prices)
    print(f"  趋势: {indicators['trend']}")
    print(f"  RSI: {indicators['rsi']:.1f}")
    print(f"  波动率: {indicators['volatility']*100:.2f}%")

    # 数学模型信号
    print("\n[2/3] 数学模型信号...")
    math_signal = strategy.generate_math_signal(indicators)
    print(f"  信号: {math_signal['signal']}")
    print(f"  置信度: {math_signal['confidence']:.2f}")

    # AI信号
    print("\n[3/3] AI信号...")
    ai_signal = strategy.generate_ai_signal(
        "Market shows bullish momentum",
        "positive sentiment"
    )
    print(f"  信号: {ai_signal['signal']}")
    print(f"  置信度: {ai_signal['confidence']:.2f}")

    # 融合信号
    print("\n" + "=" * 60)
    print("融合信号")
    print("=" * 60)
    final = strategy.fuse_signals(math_signal, ai_signal, alpha=0.6)
    print(f"最终信号: {final['signal'].upper()}")
    print(f"置信度: {final['confidence']:.2f}")

    if final['signal'] == 'long':
        print("\n✓ 建议: 做多")
    elif final['signal'] == 'short':
        print("\n✓ 建议: 做空")
    else:
        print("\n⚠ 建议: 观望")

if __name__ == "__main__":
    demo_contract_strategy()
