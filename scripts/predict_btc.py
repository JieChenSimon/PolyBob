#!/usr/bin/env python3
"""BTC预测系统 - 实时数据+技术指标+AI预测+信号融合"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import httpx
from datetime import datetime
import os

# AI预测将直接使用Claude Code会话,无需外部API

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

# ============ AI预测 ============
def ai_predict(indicators, prices):
    """AI预测未来1小时走势 - 输出提示供Claude Code分析"""
    print("\n" + "="*60)
    print("📊 请Claude Code分析以下BTC数据:")
    print("="*60)
    print(f"\n当前价格: ${indicators['price']:,.2f}")
    print(f"SMA5: ${indicators['sma5']:,.2f}")
    print(f"SMA20: ${indicators['sma20']:,.2f}")
    print(f"RSI: {indicators['rsi']:.1f}")
    print(f"MACD: {indicators['macd']:.2f}")
    print(f"布林带: ${indicators['bb_lower']:,.0f} - ${indicators['bb_upper']:,.0f}")
    print(f"\n最近10个价格: {prices[-10:].tolist()}")
    print("\n请基于以上技术指标,给出未来1小时的交易方向(long/short)和置信度(0-1)")
    print("="*60 + "\n")

    # 返回占位符,等待用户手动输入Claude的分析结果
    return {"direction": "neutral", "confidence": 0.5, "reason": "等待Claude Code分析"}

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
    alpha = 0.6  # 量化权重

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
        final_direction = "neutral"  # 观望

    return {"direction": final_direction, "confidence": final_confidence}

# ============ 主程序 ============
def main():
    print("=" * 60)
    print("BTC预测系统 - 未来1小时交易建议")
    print("=" * 60)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    # 1. 获取数据
    print("[1/4] 获取实时数据...")
    prices = get_btc_data(100)
    print(f"✓ 获取{len(prices)}根K线\n")

    # 2. 计算指标
    print("[2/4] 计算技术指标...")
    indicators = calculate_indicators(prices)
    print(f"  价格: ${indicators['price']:,.2f}")
    print(f"  RSI: {indicators['rsi']:.1f}")
    print(f"  MACD: {indicators['macd']:.2f}\n")

    # 3. 量化信号
    print("[3/4] 生成量化信号...")
    quant = quant_signal(indicators)
    print(f"  方向: {quant['direction']}")
    print(f"  置信度: {quant['confidence']:.2f}\n")

    # 4. AI预测
    print("[4/4] AI预测...")
    ai = ai_predict(indicators, prices)
    print(f"  方向: {ai['direction']}")
    print(f"  置信度: {ai['confidence']:.2f}\n")

    # 融合
    final = fuse_signals(quant, ai)

    print("=" * 60)
    print("最终建议")
    print("=" * 60)
    if final['direction'] == 'long':
        direction_text = '做多 (LONG)'
    elif final['direction'] == 'short':
        direction_text = '做空 (SHORT)'
    else:
        direction_text = '观望 (NEUTRAL)'

    print(f"\n🎯 方向: {direction_text}")
    print(f"📊 置信度: {final['confidence']*100:.0f}%")
    print(f"\n量化理由: {', '.join(quant['reasons'])}")
    print(f"AI理由: {ai.get('reason', 'N/A')}")
    print("\n" + "=" * 60)

if __name__ == "__main__":
    main()
