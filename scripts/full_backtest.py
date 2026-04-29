#!/usr/bin/env python3
"""完整回测 - 计算所有指标"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import httpx

def get_btc_data():
    """获取真实数据"""
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": "BTCUSDT", "interval": "1h", "limit": 1000}

    all_data = []
    for _ in range(3):
        r = httpx.get(url, params=params, timeout=15)
        data = r.json()
        all_data.extend(data)
        if len(data) < 1000:
            break
        params['endTime'] = int(data[0][0]) - 1

    return np.array([float(k[4]) for k in all_data])

def calculate_metrics(equity_curve, trades):
    """计算完整指标"""
    returns = np.diff(equity_curve) / equity_curve[:-1]

    # 夏普比率
    sharpe = np.mean(returns) / np.std(returns) * np.sqrt(365*24) if np.std(returns) > 0 else 0

    # 最大回撤
    peak = equity_curve[0]
    max_dd = 0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak
        if dd > max_dd:
            max_dd = dd

    # 胜率
    wins = sum(1 for t in trades if t.get('pnl', 0) > 0)
    win_rate = wins / len(trades) if trades else 0

    return {
        'sharpe': sharpe,
        'max_dd': max_dd,
        'win_rate': win_rate
    }

print("计算完整指标中...")
