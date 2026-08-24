"""Screen pre-registered long-only cross-sectional momentum on local real data."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from libs.data import run_manifest, store

COST_BPS = {"a_share": 8.0, "us_equity": 5.0, "crypto": 10.0}
CANDIDATES = tuple(
    {"lookback": lookback, "top_frac": top_frac}
    for lookback in (20, 30, 60)
    for top_frac in (0.2, 0.3)
)


def select_long_only(prices: np.ndarray, lookback: int, top_frac: float) -> np.ndarray:
    """Return causal weights; day t only ranks returns ending at t."""
    n_assets, n_days = prices.shape
    positions = np.zeros_like(prices, dtype=float)
    for day in range(lookback, n_days - 1):
        past, now = prices[:, day - lookback], prices[:, day]
        valid = (past > 0) & (now > 0) & np.isfinite(past) & np.isfinite(now)
        indices = np.flatnonzero(valid)
        if len(indices) < 4:
            continue
        scores = now[indices] / past[indices] - 1.0
        k = max(1, int(round(len(indices) * top_frac)))
        winners = indices[np.argsort(scores)[-k:]]
        positions[winners, day] = 1.0 / len(winners)
    return positions


def portfolio_result(prices: np.ndarray, positions: np.ndarray, cut: int, cost_bps: float) -> dict:
    gross = []
    net = []
    turnovers = []
    previous = np.zeros(prices.shape[0])
    for day in range(cut, prices.shape[1] - 1):
        current = positions[:, day]
        valid = (current > 0) & np.isfinite(prices[:, day]) & np.isfinite(prices[:, day + 1])
        if valid.any():
            weights = current[valid]
            weights = weights / weights.sum()
            r = prices[valid, day + 1] / prices[valid, day] - 1.0
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


def read_matrix(symbols: list[str], as_of: datetime) -> tuple[list[str], np.ndarray]:
    frames = {}
    for symbol in symbols:
        try:
            frame = store.read(store.DAILY_BARS, symbol, as_of=as_of)
            frames[symbol] = frame["close"].astype(float)
        except Exception:
            continue
    if not frames:
        return [], np.empty((0, 0))
    matrix = pd.DataFrame(frames).sort_index()
    return list(matrix.columns), matrix.to_numpy(dtype=float).T


def symbol_domain(symbol: str) -> str:
    if symbol.isdigit():
        return "a_share"
    if symbol.endswith("-USDT"):
        return "crypto"
    return "us_equity"


def main() -> int:
    as_of = datetime.now(UTC)
    manifest = run_manifest.pin("cross_sectional_local_screen", as_of=as_of,
                               params={"candidates": CANDIDATES, "cost_bps": COST_BPS})
    report = {"generated_at": datetime.now(UTC).isoformat(), "as_of": as_of.isoformat(),
              "real_data_only": True, "research_only": True,
              "parameters": {"candidates": CANDIDATES, "cost_bps": COST_BPS,
                              "oos_fraction": 0.3, "long_only": True}, "domains": {}}
    all_symbols = store.symbols(store.DAILY_BARS)
    domains = {domain: [] for domain in COST_BPS}
    for symbol in all_symbols:
        domains[symbol_domain(symbol)].append(symbol)
    for domain, symbols in domains.items():
        used, matrix = read_matrix(symbols, as_of)
        manifest.record_input(f"daily_bars:{domain}", symbols=used,
                              coverage=store.coverage(store.DAILY_BARS))
        if matrix.shape[1] < 300 or matrix.shape[0] < 4:
            report["domains"][domain] = {"status": "blocked_insufficient_data", "symbols": len(used)}
            continue
        cut = int(matrix.shape[1] * 0.7)
        test_days = np.sum(np.sum((matrix[:, cut:] > 0) & np.isfinite(matrix[:, cut:]), axis=0) >= 4)
        if test_days < 20:
            report["domains"][domain] = {
                "status": "blocked_insufficient_contemporaneous_universe",
                "symbols": len(used), "test_days_with_four_assets": int(test_days),
            }
            continue
        rows = []
        for candidate in CANDIDATES:
            positions = select_long_only(matrix, **candidate)
            result = portfolio_result(matrix, positions, cut, COST_BPS[domain])
            eligible = (matrix[:, cut] > 0) & (matrix[:, -1] > 0)
            benchmark = float(np.mean(matrix[eligible, -1] / matrix[eligible, cut] - 1.0)) if eligible.any() else None
            excess = result["oos_return"] - benchmark if benchmark is not None else None
            rows.append({**candidate, **result, "benchmark_return": benchmark,
                         "excess_return": excess,
                         "status": "screen_only" if result["oos_return"] is not None and result["oos_return"] > 0 and excess is not None and excess > 0 else "tested_no_edge"})
        report["domains"][domain] = {"status": "screened", "symbols": len(used), "rows": rows}
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
