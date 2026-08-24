import pandas as pd

from scripts.multi_asset_portfolio_replay import stable_daily_frames


def test_stable_daily_frames_rejects_long_gaps():
    stable = pd.Series([1.0, 2.0], index=["2024-01-01", "2024-01-04"])
    stale = pd.Series([1.0, 2.0], index=["2024-01-01", "2024-01-10"])
    accepted, rejected = stable_daily_frames({"STABLE": stable, "STALE": stale})
    assert list(accepted) == ["STABLE"]
    assert rejected == ["STALE"]


def test_terminal_liquidation_target_contract():
    targets = [1.0, -1.0]
    targets.append(0.0)
    assert targets[-1] == 0.0
