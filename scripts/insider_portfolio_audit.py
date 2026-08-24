"""Audit a kernel-replayed insider portfolio at the portfolio level.

The event replay reports realized PnL, but a positive event average can still be
market beta, a few tail names, or one favorable calendar period.  This audit
joins the replay equity curve to the causal SPY series and reports market beta,
CAPM-style alpha, monthly clustered inference, and calendar stability.  It is a
diagnostic gate only; promotion remains owned by ``insider_promotion_audit``.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from libs.data import store
from libs.quant.clustered_inference import analyse
from libs.quant.pbo import deflated_t_stat_threshold


def _market_returns(symbol: str, as_of: datetime) -> pd.DataFrame:
    raw = store.read(store.DAILY_BARS, symbol, as_of=as_of).sort_values(store.EVENT_DATE)
    if raw.empty:
        return pd.DataFrame(columns=["date", "market_return"])
    frame = pd.DataFrame({
        "date": [str(value) for value in raw[store.EVENT_DATE].tolist()],
        "market_close": raw["close"].astype(float).to_numpy(),
    })
    frame["market_return"] = frame["market_close"].pct_change()
    return frame[["date", "market_return"]]


def _calendar_returns(frame: pd.DataFrame) -> dict[str, dict[str, float]]:
    frame = frame.copy()
    frame["month"] = frame["date"].str[:7]
    result = {}
    for month, group in frame.groupby("month", sort=True):
        result[month] = {
            "portfolio_return": float(group["portfolio_return"].sum()),
            "market_return": float(group["market_return"].sum()),
            "alpha_return": float(group["alpha_return"].sum()),
        }
    return result


def audit(report: dict, market: pd.DataFrame, *, n_trials: int) -> dict:
    equity = pd.DataFrame(report.get("equity_curve", []))
    if equity.empty:
        raise ValueError("equity curve is missing")
    equity["date"] = equity["timestamp"].astype(str).str[:10]
    equity["portfolio_return"] = equity["equity"].astype(float).pct_change()
    frame = equity.merge(market, on="date", how="inner").dropna(
        subset=["portfolio_return", "market_return"]
    )
    if len(frame) < 60:
        raise ValueError("portfolio/market overlap is too short")
    p = frame["portfolio_return"].to_numpy(float)
    m = frame["market_return"].to_numpy(float)
    variance = float(np.var(m, ddof=1))
    beta = float(np.cov(p, m, ddof=1)[0, 1] / variance) if variance > 0 else None
    alpha = float(np.mean(p) - beta * np.mean(m)) if beta is not None else None
    frame["alpha_return"] = p - (beta * m if beta is not None else 0.0)
    threshold = deflated_t_stat_threshold(n_trials)
    clustered = analyse(
        frame["alpha_return"].tolist(), frame["date"].tolist(),
        t_hurdle=threshold, hold_days=20, cluster_by="month",
        bootstrap_draws=999, wild_draws=999, min_clusters=20,
    ).to_dict()
    equity_values = equity["equity"].astype(float).to_numpy()
    running_max = np.maximum.accumulate(equity_values)
    drawdown = 1.0 - equity_values / running_max
    calendar = _calendar_returns(frame)
    alpha_values = np.asarray([item["alpha_return"] for item in calendar.values()])
    return {
        "real_data_only": True,
        "source_report": report.get("execution_kernel"),
        "observations": int(len(frame)),
        "calendar_months": int(len(calendar)),
        "market_symbol": "SPY",
        "annualized_alpha_approx": alpha * 252 if alpha is not None else None,
        "annualized_portfolio_mean": float(np.mean(p) * 252),
        "market_beta": beta,
        "max_drawdown": float(np.max(drawdown)),
        "positive_alpha_month_fraction": float(np.mean(alpha_values > 0)) if len(alpha_values) else None,
        "median_alpha_month": float(np.median(alpha_values)) if len(alpha_values) else None,
        "calendar_returns": calendar,
        "clustered_alpha_inference": clustered,
        "candidate_family_size": n_trials,
        "status": "diagnostic_not_promotion",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="data/insider_kernel_replay_original_market20_equal_exposure.json")
    parser.add_argument("--output", default="data/insider_market20_portfolio_audit.json")
    parser.add_argument("--market-symbol", default="SPY")
    parser.add_argument("--candidate-family-size", type=int, default=108)
    args = parser.parse_args()
    report = json.loads(Path(args.report).read_text())
    market = _market_returns(args.market_symbol, datetime.now(UTC))
    result = audit(report, market, n_trials=args.candidate_family_size)
    result["source_report_path"] = args.report
    result["market_symbol"] = args.market_symbol
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"写入 {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
