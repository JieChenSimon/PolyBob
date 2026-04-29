#!/usr/bin/env python3
"""自主交易引擎 - 持续运行的模拟交易系统"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import asyncio
import numpy as np
import httpx
from datetime import datetime
import json

try:
    from anthropic import Anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

from services.auto_trader.optimizer import StrategyOptimizer

class TradingEngine:
    def __init__(self, initial_capital=10000.0):
        self.capital = initial_capital
        self.initial_capital = initial_capital
        self.position = 0.0
        self.entry_price = 0.0
        self.trades = []
        self.running = False

        # 初始化优化器
        self.optimizer = StrategyOptimizer()
        self._sync_params()

    def _sync_params(self):
        """从优化器同步参数"""
        params = self.optimizer.get_params()
        self.alpha = params['alpha']
        self.confidence_threshold = params['min_confidence']
        self.stop_loss_pct = params['stop_loss_pct']
        self.take_profit_pct = params['take_profit_pct']

    def get_btc_price(self):
        url = "https://fapi.binance.com/fapi/v1/ticker/price"
        r = httpx.get(url, params={"symbol": "BTCUSDT"}, timeout=10)
        return float(r.json()['price'])

    def get_btc_data(self, limit=100):
        url = "https://fapi.binance.com/fapi/v1/klines"
        params = {"symbol": "BTCUSDT", "interval": "5m", "limit": limit}
        r = httpx.get(url, params=params, timeout=10)
        return np.array([float(k[4]) for k in r.json()])

    def calculate_indicators(self, prices):
        sma5 = np.mean(prices[-5:])
        sma20 = np.mean(prices[-20:])
        deltas = np.diff(prices[-15:])
        gains = np.maximum(deltas, 0)
        losses = np.maximum(-deltas, 0)
        rsi = 100 - (100 / (1 + np.mean(gains) / (np.mean(losses) + 1e-10)))
        macd = prices[-12:].mean() - prices[-26:].mean()
        return {'price': prices[-1], 'sma5': sma5, 'sma20': sma20, 'rsi': rsi, 'macd': macd}

    def quant_signal(self, indicators):
        score = 0
        if indicators['sma5'] > indicators['sma20']: score += 1
        else: score -= 1
        if indicators['rsi'] < 30: score += 1
        elif indicators['rsi'] > 70: score -= 1
        if indicators['macd'] > 0: score += 1
        else: score -= 1
        direction = "long" if score > 0 else "short"
        confidence = min(abs(score) / 3.0, 1.0)
        return {"direction": direction, "confidence": confidence}

    def ai_signal(self, indicators):
        if not HAS_ANTHROPIC:
            return {"direction": "long", "confidence": 0.5}
        return {"direction": "long" if indicators['rsi'] < 50 else "short", "confidence": 0.6}

    def fuse_signals(self, quant, ai):
        if quant['direction'] == ai['direction']:
            final_direction = quant['direction']
            final_confidence = self.alpha * quant['confidence'] + (1 - self.alpha) * ai['confidence']
        else:
            final_direction = quant['direction'] if quant['confidence'] > ai['confidence'] else ai['direction']
            final_confidence = max(quant['confidence'], ai['confidence']) * 0.7
        return {"direction": final_direction if final_confidence >= self.confidence_threshold else "neutral", "confidence": final_confidence}

    def _format_trade_for_optimizer(self, trade):
        """转换交易格式供优化器使用"""
        return {
            "pnl": trade.get('pnl', 0),
            "pnl_pct": (trade.get('pnl', 0) / (trade.get('size', 1) * trade.get('price', 1))) * 100
        }

    def execute_trade(self, signal, current_price):
        if self.position == 0 and signal['direction'] == 'long':
            # Kelly仓位管理：限制最大50%
            kelly_fraction = min(signal['confidence'] * 0.5, 0.5)
            size = (self.capital * kelly_fraction) / current_price
            self.position = size
            self.entry_price = current_price
            self.capital = self.capital * (1 - kelly_fraction)
            self.trades.append({'type': 'open_long', 'price': current_price, 'size': size, 'time': datetime.now().isoformat()})
            return f"开多: {size:.4f} BTC @ ${current_price:.2f} (仓位{kelly_fraction*100:.0f}%)"
        elif self.position > 0:
            if signal['direction'] == 'short' or signal['direction'] == 'neutral':
                pnl = (current_price - self.entry_price) * self.position
                self.capital += current_price * self.position
                self.trades.append({'type': 'close_long', 'price': current_price, 'pnl': pnl, 'size': self.position, 'time': datetime.now().isoformat()})
                self.position = 0

                # 优化参数
                formatted_trades = [self._format_trade_for_optimizer(t) for t in self.trades if 'pnl' in t]
                if self.optimizer.optimize(formatted_trades):
                    self._sync_params()
                    print(">>> 参数已优化")

                return f"平多: PnL ${pnl:.2f}"
            elif (current_price - self.entry_price) / self.entry_price <= -self.stop_loss_pct:
                pnl = (current_price - self.entry_price) * self.position
                self.capital += current_price * self.position
                self.trades.append({'type': 'stop_loss', 'price': current_price, 'pnl': pnl, 'size': self.position, 'time': datetime.now().isoformat()})
                self.position = 0
                return f"止损: PnL ${pnl:.2f}"
        return None

    async def run(self):
        self.running = True
        print(f"交易引擎启动 - 初始资金: ${self.initial_capital}")
        while self.running:
            try:
                prices = self.get_btc_data(100)
                indicators = self.calculate_indicators(prices)
                quant = self.quant_signal(indicators)
                ai = self.ai_signal(indicators)
                signal = self.fuse_signals(quant, ai)

                current_price = self.get_btc_price()
                result = self.execute_trade(signal, current_price)

                total_value = self.capital + (self.position * current_price if self.position > 0 else 0)
                pnl_pct = ((total_value - self.initial_capital) / self.initial_capital) * 100

                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 价格: ${current_price:.2f} | 信号: {signal['direction']} ({signal['confidence']:.2f})")
                print(f"账户: ${total_value:.2f} | PnL: {pnl_pct:+.2f}% | 持仓: {self.position:.4f} BTC")
                if result: print(f">>> {result}")

                await asyncio.sleep(120)  # 2分钟间隔
            except Exception as e:
                print(f"错误: {e}")
                await asyncio.sleep(60)

    def stop(self):
        self.running = False

if __name__ == "__main__":
    engine = TradingEngine(10000)
    asyncio.run(engine.run())
