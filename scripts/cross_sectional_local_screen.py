"""Screen pre-registered long-only cross-sectional momentum on local real data."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from libs.data import run_manifest, store

COST_BPS = {"a_share": 8.0, "us_equity": 5.0, "crypto": 10.0}
MAX_MULTIPLE = {"a_share": 1.5, "us_equity": 1.5, "crypto": 5.0}
CANDIDATES = tuple(
    {"lookback": lookback, "top_frac": top_frac, "rebalance_days": rebalance_days}
    for lookback in (20, 30, 60)
    for top_frac in (0.2, 0.3)
    for rebalance_days in (1, 5, 10)
)
RISK_POLICIES = ("raw", "vol_target_10", "vol_target_10_dd")


def select_long_only(prices: np.ndarray, lookback: int, top_frac: float,
                     rebalance_days: int = 1) -> np.ndarray:
    """Return causal weights; day t only ranks returns ending at t."""
    n_assets, n_days = prices.shape
    positions = np.zeros_like(prices, dtype=float)
    target_k = max(1, int(round(n_assets * top_frac)))
    for day in range(lookback, n_days - 1):
        if (day - lookback) % rebalance_days and day > lookback:
            positions[:, day] = positions[:, day - 1]
            continue
        past, now = prices[:, day - lookback], prices[:, day]
        valid = (past > 0) & (now > 0) & np.isfinite(past) & np.isfinite(now)
        indices = np.flatnonzero(valid)
        if len(indices) < 4:
            continue
        scores = now[indices] / past[indices] - 1.0
        k = min(target_k, len(indices))
        winners = indices[np.argsort(scores)[-k:]]
        # Keep the target weight fixed across dates so the Paper Lab
        # position_fraction can reproduce the research portfolio exactly.
        # If fewer names are valid, the unallocated remainder stays in cash.
        positions[winners, day] = 1.0 / target_k
    return positions


def apply_risk_policy(prices: np.ndarray, positions: np.ndarray, policy: str) -> np.ndarray:
    """Apply only causal portfolio-level risk scaling; never increases exposure."""
    if policy not in RISK_POLICIES:
        raise ValueError(f"unknown risk policy: {policy}")
    scaled = np.zeros_like(positions, dtype=float)
    if policy == "raw":
        return positions.copy()
    realized: list[float] = []
    equity = 1.0
    peak = 1.0
    target_daily_vol = 0.10 / np.sqrt(252.0)
    for day in range(positions.shape[1] - 1):
        prior = np.asarray(realized[-60:], dtype=float)
        vol = float(np.std(prior, ddof=1)) if len(prior) >= 20 else 0.0
        scale = min(1.0, target_daily_vol / vol) if vol > 0 else 1.0
        drawdown = 1.0 - equity / peak if peak > 0 else 0.0
        if policy == "vol_target_10_dd":
            if drawdown >= 0.20:
                scale = 0.0
            elif drawdown >= 0.10:
                scale = min(scale, 0.5)
        scaled[:, day] = positions[:, day] * scale
        current = scaled[:, day]
        valid = (current > 0) & np.isfinite(prices[:, day]) & np.isfinite(prices[:, day + 1])
        if valid.any():
            weights = current[valid] / current[valid].sum()
            daily = float(np.dot(weights, prices[valid, day + 1] / prices[valid, day] - 1.0))
        else:
            daily = 0.0
        realized.append(daily)
        equity *= 1.0 + daily
        peak = max(peak, equity)
    return scaled


def portfolio_result(prices: np.ndarray, positions: np.ndarray, cut: int, cost_bps: float,
                     end: int | None = None, return_cap: float | None = None) -> dict:
    end = prices.shape[1] - 1 if end is None else min(end, prices.shape[1] - 1)
    gross = []
    net = []
    turnovers = []
    previous = np.zeros(prices.shape[0])
    for day in range(cut, end):
        current = positions[:, day]
        valid = (current > 0) & np.isfinite(prices[:, day]) & np.isfinite(prices[:, day + 1])
        if valid.any():
            weights = current[valid]
            weights = weights / weights.sum()
            r = prices[valid, day + 1] / prices[valid, day] - 1.0
            if return_cap is not None:
                r = np.clip(r, -return_cap, return_cap)
            gross_r = float(np.dot(weights, r))
        else:
            gross_r = 0.0
        turnover = float(np.abs(current - previous).sum())
        gross.append(gross_r)
        net.append(gross_r - turnover * cost_bps / 10_000.0)
        turnovers.append(turnover)
        previous = current
    net_arr = np.asarray(net, dtype=float)
    return {
        "oos_return": float(np.prod(1.0 + net_arr) - 1.0) if len(net_arr) else None,
        "gross_return": float(np.prod(1.0 + np.asarray(gross)) - 1.0) if gross else None,
        "mean_turnover": float(np.mean(turnovers)) if turnovers else None,
    }


def rolling_folds(prices: np.ndarray, positions: np.ndarray, cost_bps: float,
                  train_days: int = 252, test_days: int = 126) -> list[dict]:
    folds = []
    for start in range(train_days, prices.shape[1] - test_days, test_days):
        end = start + test_days
        active = np.sum(np.sum((prices[:, start:end] > 0) & np.isfinite(prices[:, start:end]), axis=0) >= 4)
        if active < 20:
            continue
        result = portfolio_result(prices, positions, start, cost_bps, end=end)
        eligible = (prices[:, start] > 0) & (prices[:, end] > 0)
        benchmark = float(np.mean(prices[eligible, end] / prices[eligible, start] - 1.0)) if eligible.any() else None
        folds.append({**result, "benchmark_return": benchmark,
                      "excess_return": result["oos_return"] - benchmark if benchmark is not None else None,
                      "start": start, "end": end})
    return folds


def read_frames(symbols: list[str], as_of: datetime) -> tuple[dict[str, pd.Series], int]:
    frames = {}
    rejected_quality = 0
    domain = symbol_domain(symbols[0]) if symbols else "us_equity"
    for symbol in symbols:
        try:
            frame = store.read(store.DAILY_BARS, symbol, as_of=as_of)
            values = frame["close"].astype(float)
            finite = values.to_numpy(dtype=float)
            if has_unresolved_price_jump(finite, MAX_MULTIPLE[domain]):
                rejected_quality += 1
                continue
            dates = frame[store.EVENT_DATE].astype(str).tolist()
            frames[symbol] = pd.Series(finite, index=dates, dtype=float)
        except Exception:
            continue
    return frames, rejected_quality


def read_matrix(symbols: list[str], as_of: datetime) -> tuple[list[str], np.ndarray, int]:
    frames, rejected_quality = read_frames(symbols, as_of)
    if not frames:
        return [], np.empty((0, 0)), rejected_quality
    matrix = align_frames(frames)
    return list(matrix.columns), matrix.to_numpy(dtype=float).T, rejected_quality


def align_frames(frames: dict[str, pd.Series]) -> pd.DataFrame:
    """Align bars by their real event date, never by source row number."""
    return pd.DataFrame(frames).sort_index()


def symbol_domain(symbol: str) -> str:
    if symbol.isdigit():
        return "a_share"
    if symbol.endswith("-USDT"):
        return "crypto"
    return "us_equity"


def has_unresolved_price_jump(values: np.ndarray, maximum: float) -> bool:
    values = np.asarray(values, dtype=float)
    if len(values) < 300 or np.any(~np.isfinite(values)) or np.any(values <= 0):
        return True
    ratios = values[1:] / values[:-1]
    return bool(np.any(ratios > maximum) or np.any(ratios < 1.0 / maximum))


def main() -> int:
    as_of = datetime.now(UTC)
    manifest = run_manifest.pin("cross_sectional_local_screen", as_of=as_of,
                               params={"candidates": CANDIDATES, "risk_policies": RISK_POLICIES,
                                       "cost_bps": COST_BPS})
    report = {"generated_at": datetime.now(UTC).isoformat(), "as_of": as_of.isoformat(),
              "real_data_only": True, "research_only": True,
              "parameters": {"candidates": CANDIDATES, "risk_policies": RISK_POLICIES, "cost_bps": COST_BPS,
                              "oos_fraction": 0.3, "long_only": True,
                              "max_single_bar_multiple": MAX_MULTIPLE}, "domains": {}}
    all_symbols = store.symbols(store.DAILY_BARS)
    domains = {domain: [] for domain in COST_BPS}
    for symbol in all_symbols:
        domains[symbol_domain(symbol)].append(symbol)
    for domain, symbols in domains.items():
        used, matrix, rejected_quality = read_matrix(symbols, as_of)
        manifest.record_input(f"daily_bars:{domain}", symbols=used,
                              coverage=store.coverage(store.DAILY_BARS))
        if matrix.shape[1] < 300 or matrix.shape[0] < 4:
            report["domains"][domain] = {"status": "blocked_insufficient_data", "symbols": len(used),
                                         "rejected_quality": rejected_quality}
            continue
        cut = int(matrix.shape[1] * 0.7)
        test_days = np.sum(np.sum((matrix[:, cut:] > 0) & np.isfinite(matrix[:, cut:]), axis=0) >= 4)
        if test_days < 20:
            report["domains"][domain] = {
                "status": "blocked_insufficient_contemporaneous_universe",
                "symbols": len(used), "rejected_quality": rejected_quality,
                "test_days_with_four_assets": int(test_days),
            }
            continue
        rows = []
        for candidate in CANDIDATES:
            base_positions = select_long_only(matrix, **candidate)
            for risk_policy in RISK_POLICIES:
                positions = apply_risk_policy(matrix, base_positions, risk_policy)
                result = portfolio_result(matrix, positions, cut, COST_BPS[domain])
                stress = portfolio_result(matrix, positions, cut, COST_BPS[domain], return_cap=0.20)
                folds = rolling_folds(matrix, positions, COST_BPS[domain])
                eligible = (matrix[:, cut] > 0) & (matrix[:, -1] > 0)
                benchmark = float(np.mean(matrix[eligible, -1] / matrix[eligible, cut] - 1.0)) if eligible.any() else None
                excess = result["oos_return"] - benchmark if benchmark is not None else None
                rows.append({**candidate, "risk_policy": risk_policy, **result, "benchmark_return": benchmark,
                         "excess_return": excess,
                         "stress_oos_return_cap_20pct": stress["oos_return"],
                         "rolling_folds": folds,
                         "rolling_median_excess": float(np.median([f["excess_return"] for f in folds])) if folds else None,
                         "status": "screen_only" if result["oos_return"] is not None and result["oos_return"] > 0 and excess is not None and excess > 0 else "tested_no_edge"})
        report["domains"][domain] = {"status": "screened", "symbols": len(used),
                                     "rejected_quality": rejected_quality, "rows": rows}
    report["manifest"] = manifest.to_dict()
    out = Path("data/cross_sectional_local_screen.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    manifest.save(out)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    print(json.dumps(report["domains"], ensure_ascii=False, indent=2))
    print(f"写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
