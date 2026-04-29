#!/usr/bin/env python3
"""快速策略验证 - 生成模拟数据并测试回测引擎"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
from datetime import datetime, timedelta
from libs.backtest.engine import BacktestEngine, BacktestConfig
from libs.schemas import Side

def generate_mock_data(n_points=1000, n_markets=2):
    """生成模拟市场数据"""
    np.random.seed(42)
    data = []

    for market_idx in range(n_markets):
        base_price = 0.5 + np.random.randn() * 0.1
        prices = base_price + np.cumsum(np.random.randn(n_points) * 0.01)
        prices = np.clip(prices, 0.1, 0.9)

        for i, price in enumerate(prices):
            spread = 0.02 + abs(np.random.randn() * 0.01)
            data.append({
                'market_id': f'market_{market_idx}',
                'timestamp': datetime.now() + timedelta(minutes=i),
                'mid_price': price,
                'bid_price': price - spread/2,
                'ask_price': price + spread/2,
                'volatility': abs(np.random.randn() * 0.02)
            })

    return sorted(data, key=lambda x: x['timestamp'])

def simple_mean_reversion_strategy(data_point, price_history):
    """简单均值回归策略"""
    market_id = data_point['market_id']
    mid_price = data_point['mid_price']

    if market_id not in price_history:
        price_history[market_id] = []

    price_history[market_id].append(mid_price)

    if len(price_history[market_id]) < 20:
        return None

    recent_prices = price_history[market_id][-20:]
    mean_price = np.mean(recent_prices)
    std_price = np.std(recent_prices)

    if std_price == 0:
        return None

    z_score = (mid_price - mean_price) / std_price

    # 价格偏离均值2个标准差时交易
    if z_score > 2.0:
        return {
            'side': Side.SELL_YES,
            'price': data_point['ask_price'],
            'size': 10.0
        }
    elif z_score < -2.0:
        return {
            'side': Side.BUY_YES,
            'price': data_point['bid_price'],
            'size': 10.0
        }

    return None

def run_validation():
    """运行快速验证"""
    print("=" * 60)
    print("PolyBob 策略快速验证")
    print("=" * 60)

    # 生成数据
    print("\n[1/4] 生成模拟数据...")
    data = generate_mock_data(n_points=500, n_markets=2)
    print(f"✓ 生成 {len(data)} 条数据点")

    # 初始化回测引擎
    print("\n[2/4] 初始化回测引擎...")
    config = BacktestConfig(
        initial_capital=10000.0,
        fee_rate=0.002,
        slippage_bps=10.0,
        use_dynamic_slippage=True
    )
    engine = BacktestEngine(config)
    print(f"✓ 初始资金: ${config.initial_capital:,.2f}")

    # 运行回测
    print("\n[3/4] 运行回测...")
    price_history = {}
    signals_generated = 0
    trades_executed = 0

    for data_point in data:
        signal = simple_mean_reversion_strategy(data_point, price_history)

        if signal:
            signals_generated += 1
            success = engine.execute_signal(
                timestamp=data_point['timestamp'],
                market_id=data_point['market_id'],
                side=signal['side'],
                price=signal['price'],
                size=signal['size'],
                volatility=data_point.get('volatility', 0.01)
            )
            if success:
                trades_executed += 1

        # 更新权益曲线
        market_prices = {}
        for d in data:
            if d['timestamp'] == data_point['timestamp']:
                market_prices[d['market_id']] = d['mid_price']

        engine.update_equity(data_point['timestamp'], market_prices)

    print(f"✓ 信号生成: {signals_generated}")
    print(f"✓ 交易执行: {trades_executed}")

    # 计算结果
    print("\n[4/4] 计算性能指标...")
    results = engine.get_results()

    if not results:
        print("✗ 无法计算结果（权益曲线为空）")
        return

    print("\n" + "=" * 60)
    print("回测结果")
    print("=" * 60)
    print(f"初始资金:     ${results['initial_capital']:,.2f}")
    print(f"最终权益:     ${results['final_equity']:,.2f}")
    print(f"总收益率:     {results['total_return_pct']:.2f}%")
    print(f"最大回撤:     {results['max_drawdown_pct']:.2f}%")
    print(f"交易次数:     {results['num_trades']}")
    print(f"总手续费:     ${results['total_fees']:.2f}")

    # 简单评估
    print("\n" + "=" * 60)
    print("策略评估")
    print("=" * 60)

    if results['total_return_pct'] > 10:
        print("✓ 收益率良好 (>10%)")
    elif results['total_return_pct'] > 0:
        print("⚠ 收益率偏低 (0-10%)")
    else:
        print("✗ 策略亏损")

    if results['max_drawdown_pct'] < 15:
        print("✓ 回撤控制良好 (<15%)")
    elif results['max_drawdown_pct'] < 25:
        print("⚠ 回撤偏高 (15-25%)")
    else:
        print("✗ 回撤过大 (>25%)")

    if results['num_trades'] > 10:
        print(f"✓ 交易频率合理 ({results['num_trades']}次)")
    else:
        print(f"⚠ 交易次数较少 ({results['num_trades']}次)")

    print("\n" + "=" * 60)
    print("结论")
    print("=" * 60)

    if results['total_return_pct'] > 10 and results['max_drawdown_pct'] < 15:
        print("✓ 策略框架验证通过！")
        print("  建议: 继续实施Phase 1（执行层+风控层）")
    elif results['total_return_pct'] > 0:
        print("⚠ 策略框架基本可用，但需要优化")
        print("  建议: 优化策略参数后再决定是否投入完整实施")
    else:
        print("✗ 策略需要重新设计")
        print("  建议: 暂缓基础设施建设，先优化策略逻辑")

if __name__ == "__main__":
    run_validation()
