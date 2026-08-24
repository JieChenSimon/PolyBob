import pandas as pd

from scripts.materialize_a_share_fundamentals import transform


def test_a_share_fundamentals_are_explicitly_non_pit():
    frame = pd.DataFrame([
        {"选项": "常用指标", "指标": "营业总收入", "20251231": 100.0},
        {"选项": "常用指标", "指标": "营业成本", "20251231": 60.0},
        {"选项": "常用指标", "指标": "归母净利润", "20251231": 20.0},
        {"选项": "常用指标", "指标": "经营现金流量净额", "20251231": 25.0},
    ])
    rows = transform("600519", frame)
    assert len(rows) == 1
    assert rows[0]["gross_profit"] == 40.0
    assert rows[0]["announcement_at"] is None
    assert rows[0]["quality_flags"]["strict_historical_pit"] is False
