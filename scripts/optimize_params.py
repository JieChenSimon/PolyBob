#!/usr/bin/env python3
"""参数优化 - 寻找最佳策略参数"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
from datetime import datetime

def generate_cointegrated_data(n=1000):
    """生成协整的价格序列"""
    np.random.seed(42)
    common_trend = np.cumsum(np.random.randn(n) * 0.01)
    noise1 = np.random.randn(n) * 0.005
    prices1 = 0.5 + common_trend + noise1
    noise2 = np.random.randn(n) * 0.005
    prices2 = 0.4 + 1.2 * common_trend + noise2
    prices1 = np.clip(prices1, 0.1, 0.9)
    prices2 = np.clip(prices2, 0.1, 0.9)
    return prices1, prices2

def calculate_hedge_ratio(y, x):
    """计算对冲比率"""
    X = np.vstack([x, np.ones(len(x))]).T
    beta, alpha = np.linalg.lstsq(X, y, rcond=None)[0]
    return beta

def calculate_zscore(spread, window=20):
    """计算Z-score"""
    if len(spread) < window:
        return 0.0
    recent = spread[-window:]
    mean = np.mean(recent)
    std = np.std(recent)
    return (spread[-1] - mean) / std if std > 0 else 0.0

def backtest_strategy(prices1, prices2, entry_threshold, exit_threshold, lookback):
    """回测单组参数"""
    capital = 10000.0
    position1 = 0.0
    position2 = 0.0
    equity_curve = [capital]

    for i in range(lookback, len(prices1)):
        y = prices1[max(0, i-lookback):i+1]
        x = prices2[max(0, i-lookback):i+1]

        beta = calculate_hedge_ratio(y, x)
        spread = y - beta * x
        zscore = calculate_zscore(spread)

        if abs(position1) == 0:
            if zscore > entry_threshold:
                size = 100.0
                position1 = -size
                position2 = size * beta
                cost = size * prices1[i] - size * beta * prices2[i]
                capital -= abs(cost) * 0.002
            elif zscore < -entry_threshold:
                size = 100.0
                position1 = size
                position2 = -size * beta
                cost = size * prices1[i] + size * beta * prices2[i]
                capital -= abs(cost) * 0.002
        else:
            if abs(zscore) < exit_threshold:
                pnl = position1 * prices1[i] + position2 * prices2[i]
                capital += pnl
                capital -= abs(pnl) * 0.002
                position1 = 0.0
                position2 = 0.0

        equity = capital + position1 * prices1[i] + position2 * prices2[i]
        equity_curve.append(equity)

    # 计算指标
    returns = np.diff(equity_curve) / equity_curve[:-1]
    sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0

    peak = 10000
    max_dd = 0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak
        if dd > max_dd:
            max_dd = dd

    return sharpe, max_dd, equity_curve[-1]

def optimize_parameters():
    """参数优化"""
    print("=" * 60)
    print("策略参数优化")
    print("=" * 60)

    prices1, prices2 = generate_cointegrated_data(1000)

    best_sharpe = -999
    best_params = None
    results = []

    print("\n搜索最佳参数...")

    for entry in [1.5, 2.0, 2.5]:
        for exit in [0.3, 0.5, 0.7]:
            for lookback in [30, 50, 80]:
                sharpe, dd, final = backtest_strategy(
                    prices1, prices2, entry, exit, lookback
                )

                results.append({
                    'entry': entry,
                    'exit': exit,
                    'lookback': lookback,
                    'sharpe': sharpe,
                    'dd': dd,
                    'final': final
                })

                if sharpe > best_sharpe:
                    best_sharpe = sharpe
                    best_params = (entry, exit, lookback)

    print(f"\n✓ 测试了 {len(results)} 组参数")

    print("\n" + "=" * 60)
    print("最佳参数")
    print("=" * 60)
    print(f"入场阈值:     {best_params[0]} std")
    print(f"出场阈值:     {best_params[1]} std")
    print(f"回看窗口:     {best_params[2]} 期")
    print(f"夏普比率:     {best_sharpe:.2f}")

    # 显示Top 5
    print("\n" + "=" * 60)
    print("Top 5 参数组合")
    print("=" * 60)
    sorted_results = sorted(results, key=lambda x: x['sharpe'], reverse=True)[:5]

    for i, r in enumerate(sorted_results, 1):
        print(f"\n#{i}: 夏普={r['sharpe']:.2f}, 回撤={r['dd']*100:.1f}%")
        print(f"    entry={r['entry']}, exit={r['exit']}, lookback={r['lookback']}")

    return best_params, best_sharpe

if __name__ == "__main__":
    params, sharpe = optimize_parameters()
