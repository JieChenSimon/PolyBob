"""
简化融合策略回测 - 专注核心逻辑
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
from datetime import datetime, timedelta

# 生成测试数据
np.random.seed(42)
prices = [0.50]
for i in range(500):
    if i < 100: trend = 0.0015
    elif i < 200: trend = -0.001
    elif i < 350: trend = 0.0012
    else: trend = -0.0008

    price = prices[-1] * (1 + trend + np.random.normal(0, 0.002))
    prices.append(max(0.1, min(0.9, price)))

# 策略信号
def quant_signal(prices, i):
    if i < 20: return 0
    fast = np.mean(prices[i-5:i])
    slow = np.mean(prices[i-20:i])
    if fast > slow * 1.001: return 1
    if fast < slow * 0.999: return -1
    return 0

def ai_signal(prices, i):
    if i < 12: return 0
    momentum = (prices[i] - prices[i-12]) / prices[i-12]
    if momentum > 0.005: return 1
    if momentum < -0.005: return -1
    return 0

# 融合回测
def backtest(alpha):
    capital = 10000
    position = 0
    trades = []
    equity = [capital]

    for i in range(1, len(prices)):
        q_sig = quant_signal(prices, i)
        a_sig = ai_signal(prices, i)

        # 融合信号
        combined = alpha * q_sig + (1-alpha) * a_sig
        signal = 1 if combined > 0.5 else (-1 if combined < -0.5 else 0)

        # 交易逻辑
        if signal == 1 and position <= 0:
            size = 100
            cost = size * prices[i] * 1.001  # 手续费
            if cost < capital:
                capital -= cost
                position = size
                trades.append(('buy', prices[i], size))
        elif signal == -1 and position > 0:
            capital += position * prices[i] * 0.999
            trades.append(('sell', prices[i], position))
            position = 0

        # 更新权益
        equity.append(capital + position * prices[i])

    # 计算指标
    returns = np.diff(equity) / equity[:-1]
    total_return = (equity[-1] - equity[0]) / equity[0]
    sharpe = np.mean(returns) / (np.std(returns) + 1e-6) * np.sqrt(252)

    # 最大回撤
    peak = equity[0]
    max_dd = 0
    for e in equity:
        if e > peak: peak = e
        dd = (peak - e) / peak
        if dd > max_dd: max_dd = dd

    # 胜率
    wins = sum(1 for t in trades if t[0] == 'sell' and len([x for x in trades if x[0]=='buy']) > 0)
    win_rate = wins / (len(trades)/2) if len(trades) > 0 else 0

    return {
        'total_return': total_return,
        'sharpe': sharpe,
        'max_dd': max_dd,
        'trades': len(trades),
        'win_rate': win_rate
    }

# 优化权重
print("=== 融合策略回测优化 ===\n")
best_alpha = 0.5
best_sharpe = -999
best_result = None

for alpha in np.arange(0.2, 0.9, 0.1):
    result = backtest(alpha)
    print(f"α={alpha:.1f}: 收益={result['total_return']*100:.2f}%, "
          f"夏普={result['sharpe']:.2f}, 回撤={result['max_dd']*100:.2f}%, "
          f"交易={result['trades']}")

    if result['sharpe'] > best_sharpe:
        best_sharpe = result['sharpe']
        best_alpha = alpha
        best_result = result

print(f"\n{'='*60}")
print("最优结果")
print(f"{'='*60}")
print(f"最优权重 α: {best_alpha:.2f}")
print(f"总收益率: {best_result['total_return']*100:.2f}%")
print(f"夏普比率: {best_result['sharpe']:.2f}")
print(f"最大回撤: {best_result['max_dd']*100:.2f}%")
print(f"胜率: {best_result['win_rate']*100:.2f}%")
print(f"交易次数: {best_result['trades']}")
print(f"{'='*60}")

# 保存结果
import json
output = Path(__file__).parent.parent / "data" / "fusion_backtest_result.json"
with open(output, 'w') as f:
    json.dump({
        'best_alpha': float(best_alpha),
        'sharpe_ratio': float(best_result['sharpe']),
        'total_return': float(best_result['total_return']),
        'win_rate': float(best_result['win_rate']),
        'max_drawdown': float(best_result['max_dd'])
    }, f, indent=2)

print(f"\n✓ 结果已保存到 {output}")
