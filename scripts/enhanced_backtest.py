#!/usr/bin/env python3
"""增强策略回测 - 使用协整和均值回归"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict, deque

def generate_cointegrated_data(n=1000):
    """生成协整的价格序列"""
    np.random.seed(42)

    # 生成共同趋势
    common_trend = np.cumsum(np.random.randn(n) * 0.01)

    # 市场1: 基础价格 + 共同趋势
    noise1 = np.random.randn(n) * 0.005
    prices1 = 0.5 + common_trend + noise1

    # 市场2: 协整关系 (beta=1.2)
    noise2 = np.random.randn(n) * 0.005
    prices2 = 0.4 + 1.2 * common_trend + noise2

    # 限制在[0.1, 0.9]
    prices1 = np.clip(prices1, 0.1, 0.9)
    prices2 = np.clip(prices2, 0.1, 0.9)

    return prices1, prices2

def calculate_hedge_ratio(y, x):
    """计算对冲比率 (OLS)"""
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

def run_enhanced_backtest():
    """运行增强回测"""
    print("=" * 60)
    print("增强统计套利策略回测")
    print("=" * 60)

    # 生成数据
    print("\n[1/4] 生成协整数据...")
    prices1, prices2 = generate_cointegrated_data(1000)
    print(f"✓ 生成 {len(prices1)} 条价格数据")

    # 初始化
    print("\n[2/4] 初始化策略...")
    capital = 10000.0
    position1 = 0.0
    position2 = 0.0
    trades = []
    equity_curve = [capital]

    entry_threshold = 2.0
    exit_threshold = 0.5
    lookback = 50

    print(f"✓ 初始资金: ${capital:,.2f}")
    print(f"✓ 入场阈值: {entry_threshold} std")
    print(f"✓ 出场阈值: {exit_threshold} std")

    # 回测
    print("\n[3/4] 运行回测...")
    for i in range(lookback, len(prices1)):
        y = prices1[max(0, i-lookback):i+1]
        x = prices2[max(0, i-lookback):i+1]

        # 计算对冲比率和价差
        beta = calculate_hedge_ratio(y, x)
        spread = y - beta * x
        zscore = calculate_zscore(spread)

        # 交易逻辑
        if abs(position1) == 0:  # 无持仓
            if zscore > entry_threshold:
                # 做空价差: 卖出市场1，买入市场2
                size = 100.0
                position1 = -size
                position2 = size * beta
                cost = size * prices1[i] - size * beta * prices2[i]
                capital -= cost * 0.002  # 手续费
                trades.append({
                    'type': 'open_short',
                    'i': i,
                    'zscore': zscore,
                    'beta': beta
                })
            elif zscore < -entry_threshold:
                # 做多价差: 买入市场1，卖出市场2
                size = 100.0
                position1 = size
                position2 = -size * beta
                cost = size * prices1[i] + size * beta * prices2[i]
                capital -= cost * 0.002
                trades.append({
                    'type': 'open_long',
                    'i': i,
                    'zscore': zscore,
                    'beta': beta
                })
        else:  # 有持仓
            if abs(zscore) < exit_threshold:
                # 平仓
                pnl = position1 * prices1[i] + position2 * prices2[i]
                capital += pnl
                capital -= abs(pnl) * 0.002
                trades.append({
                    'type': 'close',
                    'i': i,
                    'zscore': zscore,
                    'pnl': pnl
                })
                position1 = 0.0
                position2 = 0.0

        # 更新权益
        equity = capital + position1 * prices1[i] + position2 * prices2[i]
        equity_curve.append(equity)

    print(f"✓ 交易次数: {len(trades)}")

    # 计算指标
    print("\n[4/4] 计算性能指标...")
    final_equity = equity_curve[-1]
    total_return = (final_equity - 10000) / 10000

    # 最大回撤
    peak = 10000
    max_dd = 0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak
        if dd > max_dd:
            max_dd = dd

    # 夏普比率 (简化)
    returns = np.diff(equity_curve) / equity_curve[:-1]
    sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0

    print("\n" + "=" * 60)
    print("回测结果")
    print("=" * 60)
    print(f"初始资金:     ${10000:,.2f}")
    print(f"最终权益:     ${final_equity:,.2f}")
    print(f"总收益率:     {total_return*100:.2f}%")
    print(f"最大回撤:     {max_dd*100:.2f}%")
    print(f"夏普比率:     {sharpe:.2f}")
    print(f"交易次数:     {len(trades)}")

    print("\n" + "=" * 60)
    print("策略评估")
    print("=" * 60)

    if sharpe > 1.5:
        print("✓ 夏普比率优秀 (>1.5)")
        status = "excellent"
    elif sharpe > 1.0:
        print("⚠ 夏普比率良好 (1.0-1.5)")
        status = "good"
    else:
        print("✗ 夏普比率不足 (<1.0)")
        status = "poor"

    if max_dd < 0.15:
        print("✓ 回撤控制良好 (<15%)")
    else:
        print("✗ 回撤过大 (>15%)")

    print("\n" + "=" * 60)
    print("结论")
    print("=" * 60)

    if status == "excellent":
        print("✓ 策略表现优秀！建议启动Phase 1完整实施")
    elif status == "good":
        print("⚠ 策略表现良好，可以考虑小规模实盘测试")
    else:
        print("✗ 策略需要进一步优化")

    return sharpe, max_dd

if __name__ == "__main__":
    sharpe, dd = run_enhanced_backtest()
