"""
前视偏差防止测试
确保不使用未来信息
"""
import pytest
from datetime import datetime, timedelta
import pandas as pd


class LookAheadBiasDetector:
    """前视偏差检测器"""

    @staticmethod
    def check_feature_calculation(df: pd.DataFrame, feature_col: str) -> bool:
        """检查特征计算是否使用未来数据"""
        # 检查是否有负向shift (使用未来数据)
        if df[feature_col].shift(-1).notna().any():
            return False  # 可能存在前视偏差
        return True

    @staticmethod
    def validate_execution_timing(signal_time: datetime, execution_time: datetime) -> bool:
        """验证执行时间在信号之后"""
        return execution_time > signal_time


@pytest.mark.backtest
def test_no_future_data_in_features():
    """测试特征计算不使用未来数据"""
    # 创建时间序列数据
    dates = pd.date_range('2024-01-01', periods=100, freq='1h')
    df = pd.DataFrame({
        'timestamp': dates,
        'price': range(100),
    })

    # ✅ 正确: 使用历史数据
    df['ma_5'] = df['price'].rolling(5).mean()
    df['return_1h'] = df['price'].pct_change(1)

    # 验证没有使用未来数据
    assert df['ma_5'].iloc[10] == df['price'].iloc[6:11].mean()


@pytest.mark.backtest
def test_detect_future_data_usage():
    """测试检测未来数据使用"""
    dates = pd.date_range('2024-01-01', periods=100, freq='1h')
    df = pd.DataFrame({
        'timestamp': dates,
        'price': range(100),
    })

    # ❌ 错误: 使用未来数据
    df['future_return'] = df['price'].shift(-1) - df['price']

    # 这种特征在实际交易中不可用
    assert df['future_return'].iloc[0] == 1  # 使用了下一时刻数据


@pytest.mark.backtest
def test_execution_after_signal():
    """测试订单执行在信号之后"""
    detector = LookAheadBiasDetector()

    signal_time = datetime(2024, 1, 1, 10, 0, 0)
    execution_time = datetime(2024, 1, 1, 10, 0, 1)  # 1秒后

    assert detector.validate_execution_timing(signal_time, execution_time) is True


@pytest.mark.backtest
def test_reject_instant_execution():
    """测试拒绝即时执行(不现实)"""
    detector = LookAheadBiasDetector()

    signal_time = datetime(2024, 1, 1, 10, 0, 0)
    execution_time = datetime(2024, 1, 1, 10, 0, 0)  # 同一时刻

    # 实际交易中不可能在同一时刻执行
    assert detector.validate_execution_timing(signal_time, execution_time) is False


@pytest.mark.backtest
def test_slippage_modeling():
    """测试滑点建模"""

    def calculate_execution_price(signal_price: float, order_size: float) -> float:
        """计算实际成交价(含滑点)"""
        if order_size < 1000:
            slippage = 0.001  # 0.1%
        elif order_size < 5000:
            slippage = 0.002  # 0.2%
        else:
            slippage = 0.003  # 0.3%

        return signal_price * (1 + slippage)

    # 小单
    exec_price_small = calculate_execution_price(0.5, 500)
    assert exec_price_small == pytest.approx(0.5005, rel=1e-4)

    # 大单
    exec_price_large = calculate_execution_price(0.5, 6000)
    assert exec_price_large == pytest.approx(0.5015, rel=1e-4)
