#!/usr/bin/env python3
"""BTC预测系统 - 集成Claude Code AI分析"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import httpx
from datetime import datetime

# ============ 数据获取 ============
def get_btc_data(limit=100):
    """获取BTC实时数据"""
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": "BTCUSDT", "interval": "5m", "limit": limit}
    r = httpx.get(url, params=params, timeout=10)
    data = r.json()
    return np.array([float(k[4]) for k in data])

# ============ 技术指标 ============
def calculate_indicators(prices):
    """计算所有技术指标"""
    current = prices[-1]
    sma5 = np.mean(prices[-5:])
    sma20 = np.mean(prices[-20:])

    # RSI
    deltas = np.diff(prices[-15:])
    gains = np.maximum(deltas, 0)
    losses = np.maximum(-deltas, 0)
    rsi = 100 - (100 / (1 + np.mean(gains) / (np.mean(losses) + 1e-10)))

    # MACD
    ema12 = prices[-12:].mean()
    ema26 = prices[-26:].mean()
    macd = ema12 - ema26

    # 布林带
    bb_mid = np.mean(prices[-20:])
    bb_std = np.std(prices[-20:])
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std

    return {
        'price': current,
        'sma5': sma5,
        'sma20': sma20,
        'rsi': rsi,
        'macd': macd,
        'bb_upper': bb_upper,
        'bb_lower': bb_lower,
        'bb_mid': bb_mid
    }

# ============ 量化信号 ============
def quant_signal(indicators):
    """传统量化信号"""
    score = 0
    reasons = []

    if indicators['sma5'] > indicators['sma20']:
        score += 1
        reasons.append("均线多头")
    else:
        score -= 1
        reasons.append("均线空头")

    if indicators['rsi'] < 30:
        score += 1
        reasons.append("RSI超卖")
    elif indicators['rsi'] > 70:
        score -= 1
        reasons.append("RSI超买")

    if indicators['macd'] > 0:
        score += 1
        reasons.append("MACD多头")
    else:
        score -= 1
        reasons.append("MACD空头")

    if indicators['price'] < indicators['bb_lower']:
        score += 1
        reasons.append("布林带下轨")
    elif indicators['price'] > indicators['bb_upper']:
        score -= 1
        reasons.append("布林带上轨")

    direction = "long" if score > 0 else "short"
    confidence = min(abs(score) / 4.0, 1.0)
    return {"direction": direction, "confidence": confidence, "reasons": reasons}

# ============ 信号融合 ============
def fuse_signals(quant, ai):
    """融合量化和AI信号"""
    alpha = 0.4  # 量化权重40%, AI权重60%

    # 方向一致性
    if quant['direction'] == ai['direction']:
        final_direction = quant['direction']
        final_confidence = alpha * quant['confidence'] + (1 - alpha) * ai['confidence']
    else:
        # 方向冲突,选置信度高的
        if quant['confidence'] > ai['confidence']:
            final_direction = quant['direction']
            final_confidence = quant['confidence'] * 0.7
        else:
            final_direction = ai['direction']
            final_confidence = ai['confidence'] * 0.7

    # 置信度阈值判断
    if final_confidence < 0.5:
        final_direction = "neutral"

    return {"direction": final_direction, "confidence": final_confidence}

# ============ 主程序 ============
def main():
    print("=" * 60)
    print("BTC预测系统 - Claude Code AI增强版")
    print("=" * 60)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    # 1. 获取数据
    print("[1/3] 获取实时数据...")
    prices = get_btc_data(100)
    print(f"✓ 获取{len(prices)}根K线\n")

    # 2. 计算指标
    print("[2/3] 计算技术指标...")
    indicators = calculate_indicators(prices)
    print(f"  价格: ${indicators['price']:,.2f}")
    print(f"  RSI: {indicators['rsi']:.1f}")
    print(f"  MACD: {indicators['macd']:.2f}\n")

    # 3. 量化信号
    print("[3/3] 生成量化信号...")
    quant = quant_signal(indicators)
    print(f"  方向: {quant['direction']}")
    print(f"  置信度: {quant['confidence']:.2f}\n")

    # 4. Claude AI分析 (手动输入)
    print("=" * 60)
    print("Claude Code AI分析")
    print("=" * 60)
    ai = {
        "direction": "short",
        "confidence": 0.65,
        "reason": "价格空头排列+MACD强烈空头+RSI偏弱+下行趋势明显"
    }
    print(f"  方向: {ai['direction']}")
    print(f"  置信度: {ai['confidence']:.2f}")
    print(f"  理由: {ai['reason']}\n")

    # 融合
    final = fuse_signals(quant, ai)

    print("=" * 60)
    print("最终建议")
    print("=" * 60)
    if final['direction'] == 'long':
        direction_text = '做多 (LONG)'
        emoji = '📈'
    elif final['direction'] == 'short':
        direction_text = '做空 (SHORT)'
        emoji = '📉'
    else:
        direction_text = '观望 (NEUTRAL)'
        emoji = '⏸️'

    print(f"\n{emoji} 方向: {direction_text}")
    print(f"📊 置信度: {final['confidence']*100:.0f}%")
    print(f"\n量化理由: {', '.join(quant['reasons'])}")
    print(f"AI理由: {ai['reason']}")
    print("\n" + "=" * 60)

if __name__ == "__main__":
    main()
