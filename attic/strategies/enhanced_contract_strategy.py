"""增强版BTC合约交易策略 - MACD + 布林带 + 优化信号融合"""
import numpy as np
from typing import Dict, Optional, Tuple


class EnhancedContractStrategy:
    """增强版合约交易策略"""

    def __init__(
        self,
        ma_short: int = 5,
        ma_long: int = 20,
        rsi_period: int = 14,
        bb_period: int = 20,
        bb_std: float = 2.0,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9
    ):
        self.ma_short = ma_short
        self.ma_long = ma_long
        self.rsi_period = rsi_period
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal

    def _ema(self, data: np.ndarray, period: int) -> float:
        """计算指数移动平均"""
        if len(data) < period:
            return np.mean(data)
        alpha = 2 / (period + 1)
        ema = data[0]
        for price in data[1:]:
            ema = alpha * price + (1 - alpha) * ema
        return ema

    def calculate_macd(self, prices: np.ndarray) -> Dict:
        """计算MACD指标"""
        if len(prices) < self.macd_slow:
            return {'macd': 0, 'signal': 0, 'histogram': 0}

        ema_fast = self._ema(prices, self.macd_fast)
        ema_slow = self._ema(prices, self.macd_slow)
        macd_line = ema_fast - ema_slow

        # 简化：用最近9个MACD值计算信号线
        macd_values = []
        for i in range(max(0, len(prices) - self.macd_signal), len(prices)):
            if i >= self.macd_slow:
                ef = self._ema(prices[:i+1], self.macd_fast)
                es = self._ema(prices[:i+1], self.macd_slow)
                macd_values.append(ef - es)

        signal_line = np.mean(macd_values) if macd_values else 0
        histogram = macd_line - signal_line

        return {
            'macd': macd_line,
            'signal': signal_line,
            'histogram': histogram
        }

    def calculate_bollinger_bands(self, prices: np.ndarray) -> Dict:
        """计算布林带"""
        if len(prices) < self.bb_period:
            return {'upper': 0, 'middle': 0, 'lower': 0, 'width': 0}

        middle = np.mean(prices[-self.bb_period:])
        std = np.std(prices[-self.bb_period:])
        upper = middle + self.bb_std * std
        lower = middle - self.bb_std * std

        return {
            'upper': upper,
            'middle': middle,
            'lower': lower,
            'width': (upper - lower) / middle if middle > 0 else 0
        }

    def calculate_rsi(self, prices: np.ndarray) -> float:
        """计算RSI"""
        if len(prices) < self.rsi_period + 1:
            return 50.0

        deltas = np.diff(prices)
        gains = np.maximum(deltas, 0)
        losses = np.maximum(-deltas, 0)

        avg_gain = np.mean(gains[-self.rsi_period:])
        avg_loss = np.mean(losses[-self.rsi_period:])

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def calculate_indicators(self, prices: np.ndarray) -> Dict:
        """计算所有技术指标"""
        if len(prices) < self.ma_long:
            return {}

        current_price = prices[-1]
        ma_short = np.mean(prices[-self.ma_short:])
        ma_long = np.mean(prices[-self.ma_long:])
        rsi = self.calculate_rsi(prices)
        macd = self.calculate_macd(prices)
        bb = self.calculate_bollinger_bands(prices)

        return {
            'price': current_price,
            'ma_short': ma_short,
            'ma_long': ma_long,
            'rsi': rsi,
            'macd': macd,
            'bb': bb
        }

    def generate_signal(self, indicators: Dict) -> Dict:
        """生成交易信号"""
        if not indicators:
            return {'signal': 'neutral', 'confidence': 0, 'reason': 'no_data'}

        price = indicators['price']
        ma_short = indicators['ma_short']
        ma_long = indicators['ma_long']
        rsi = indicators['rsi']
        macd = indicators['macd']
        bb = indicators['bb']

        # 信号评分系统
        score = 0
        reasons = []

        # 1. 趋势信号 (MA)
        if ma_short > ma_long:
            score += 1
            reasons.append('ma_bullish')
        elif ma_short < ma_long:
            score -= 1
            reasons.append('ma_bearish')

        # 2. RSI信号
        if rsi < 30:
            score += 1
            reasons.append('rsi_oversold')
        elif rsi > 70:
            score -= 1
            reasons.append('rsi_overbought')

        # 3. MACD信号
        if macd['histogram'] > 0 and macd['macd'] > macd['signal']:
            score += 1
            reasons.append('macd_bullish')
        elif macd['histogram'] < 0 and macd['macd'] < macd['signal']:
            score -= 1
            reasons.append('macd_bearish')

        # 4. 布林带信号
        if price < bb['lower']:
            score += 1
            reasons.append('bb_oversold')
        elif price > bb['upper']:
            score -= 1
            reasons.append('bb_overbought')

        # 信号融合
        confidence = min(abs(score) / 4.0, 1.0)

        if score >= 2:
            return {'signal': 'long', 'confidence': confidence, 'reason': ','.join(reasons)}
        elif score <= -2:
            return {'signal': 'short', 'confidence': confidence, 'reason': ','.join(reasons)}
        return {'signal': 'neutral', 'confidence': 0, 'reason': 'weak_signal'}

    def optimize_parameters(
        self,
        prices: np.ndarray,
        returns: np.ndarray,
        param_ranges: Optional[Dict] = None
    ) -> Dict:
        """参数优化"""
        if param_ranges is None:
            param_ranges = {
                'ma_short': [3, 5, 7],
                'ma_long': [15, 20, 25],
                'rsi_period': [10, 14, 20],
                'bb_std': [1.5, 2.0, 2.5]
            }

        best_sharpe = -np.inf
        best_params = {}

        for ma_s in param_ranges['ma_short']:
            for ma_l in param_ranges['ma_long']:
                if ma_s >= ma_l:
                    continue
                for rsi_p in param_ranges['rsi_period']:
                    for bb_s in param_ranges['bb_std']:
                        # 临时设置参数
                        self.ma_short = ma_s
                        self.ma_long = ma_l
                        self.rsi_period = rsi_p
                        self.bb_std = bb_s

                        # 回测
                        sharpe = self._backtest(prices, returns)

                        if sharpe > best_sharpe:
                            best_sharpe = sharpe
                            best_params = {
                                'ma_short': ma_s,
                                'ma_long': ma_l,
                                'rsi_period': rsi_p,
                                'bb_std': bb_s,
                                'sharpe': sharpe
                            }

        return best_params

    def _backtest(self, prices: np.ndarray, returns: np.ndarray) -> float:
        """简单回测计算夏普比率"""
        if len(prices) < self.ma_long + 10:
            return -np.inf

        strategy_returns = []

        for i in range(self.ma_long, len(prices) - 1):
            indicators = self.calculate_indicators(prices[:i+1])
            signal = self.generate_signal(indicators)

            if signal['signal'] == 'long':
                strategy_returns.append(returns[i])
            elif signal['signal'] == 'short':
                strategy_returns.append(-returns[i])

        if len(strategy_returns) < 10:
            return -np.inf

        mean_return = np.mean(strategy_returns)
        std_return = np.std(strategy_returns)

        if std_return == 0:
            return -np.inf

        return mean_return / std_return * np.sqrt(252)
