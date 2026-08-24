import numpy as np
import pandas as pd
import pytest

from scripts.insider_portfolio_audit import audit


def test_portfolio_audit_separates_market_beta_from_alpha():
    dates = [f"2024-{month:02d}-{day:02d}" for month in (1, 2, 3, 4)
             for day in range(1, 21)]
    market = np.linspace(100.0, 110.0, len(dates))
    market_returns = np.concatenate([[0.0], np.diff(market) / market[:-1]])
    portfolio = 100_000.0 * np.cumprod(1.0 + 0.5 * market_returns)
    report = {"equity_curve": [
        {"timestamp": f"{date}T00:00:00+00:00", "equity": float(value)}
        for date, value in zip(dates, portfolio)
    ], "execution_kernel": "SimulationService"}
    market_frame = pd.DataFrame({
        "date": dates, "market_return": market_returns,
    })
    result = audit(report, market_frame, n_trials=18)
    assert result["market_beta"] == pytest.approx(0.5, rel=0.05)
    assert result["observations"] == len(dates) - 1
