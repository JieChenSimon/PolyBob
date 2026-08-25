"""Screen pre-registered long-only cross-sectional momentum on local real data."""

from __future__ import annotations

import json
import argparse
import resource
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from libs.data import run_manifest, store


class CpuBudgetThrottle:
    """Throttle per-symbol materialization so large universes stay cooperative."""

    def __init__(self, target: float = 0.30):
        self.target = min(0.50, max(0.05, float(target)))
        self._wall = time.monotonic()
        self._cpu = self._cpu_seconds()

    @staticmethod
    def _cpu_seconds() -> float:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        return float(usage.ru_utime + usage.ru_stime)

    def pause(self) -> None:
        wall = time.monotonic() - self._wall
        cpu = self._cpu_seconds() - self._cpu
        if wall >= 0.05 and cpu > 0:
            desired_wall = cpu / self.target
            if desired_wall > wall:
                time.sleep(min(desired_wall - wall, 2.0))
        self._wall = time.monotonic()
        self._cpu = self._cpu_seconds()

COST_BPS = {"a_share": 8.0, "us_equity": 5.0, "crypto": 10.0}
MAX_MULTIPLE = {"a_share": 1.5, "us_equity": 1.5, "crypto": 5.0}
CANDIDATES = tuple(
    {"lookback": lookback, "top_frac": top_frac, "rebalance_days": rebalance_days}
    for lookback in (20, 30, 60)
    for top_frac in (0.2, 0.3)
    for rebalance_days in (1, 5, 10)
)
RISK_POLICIES = (
    "raw", "vol_target_10", "vol_target_10_dd", "vol_target_10_dd_recovery",
)
MIN_BENCHMARK_ASSETS = 20
DD_RECOVERY_COOLDOWN_BARS = 20
DD_RECOVERY_SCALE = 0.25


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
    risk_off_remaining = 0
    recovering = False
    target_daily_vol = 0.10 / np.sqrt(252.0)
    for day in range(positions.shape[1] - 1):
        prior = np.asarray(realized[-60:], dtype=float)
        vol = float(np.std(prior, ddof=1)) if len(prior) >= 20 else 0.0
        scale = min(1.0, target_daily_vol / vol) if vol > 0 else 1.0
        drawdown = 1.0 - equity / peak if peak > 0 else 0.0
        if policy in {"vol_target_10_dd", "vol_target_10_dd_recovery"}:
            if drawdown >= 0.20:
                if policy == "vol_target_10_dd":
                    scale = 0.0
                elif risk_off_remaining == 0 and not recovering:
                    risk_off_remaining = DD_RECOVERY_COOLDOWN_BARS
                    recovering = True
                if risk_off_remaining > 0:
                    scale = 0.0
                    risk_off_remaining -= 1
                else:
                    scale = min(scale, DD_RECOVERY_SCALE)
            elif drawdown >= 0.10:
                scale = min(scale, DD_RECOVERY_SCALE if recovering else 0.5)
            elif recovering:
                scale = min(scale, DD_RECOVERY_SCALE)
                # Recovery is complete only after the high-water drawdown is
                # below 10%; this prevents an immediate full-risk jump.
                if drawdown < 0.10:
                    recovering = False
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


def _endpoint_values(prices: np.ndarray, index: int, *, max_stale_bars: int = 5) -> np.ndarray:
    """Return last known prices at or before an endpoint within a short gap.

    Assets do not all print on the same calendar date: exchanges close on
    different holidays and the provider may finish a bar at a different UTC
    date. Requiring an exact matrix row silently reduced the US benchmark to
    three names. Looking backward only (never forward) keeps the comparison
    causal while allowing a bounded stale mark; names without such a mark stay
    unknown.
    """
    if index < 0 or index >= prices.shape[1]:
        return np.full(prices.shape[0], np.nan)
    values = np.full(prices.shape[0], np.nan)
    for offset in range(max(0, int(max_stale_bars)) + 1):
        column = index - offset
        if column < 0:
            break
        candidate = prices[:, column]
        missing = ~np.isfinite(values)
        valid = missing & np.isfinite(candidate) & (candidate > 0)
        values[valid] = candidate[valid]
    return values


def equal_weight_benchmark(prices: np.ndarray, start: int, end: int,
                           *, max_stale_bars: int = 5) -> float | None:
    """Equal-weight buy-and-hold return over a real contiguous window."""
    if end <= start or end >= prices.shape[1]:
        return None
    start_values = _endpoint_values(prices, start, max_stale_bars=max_stale_bars)
    end_values = _endpoint_values(prices, end, max_stale_bars=max_stale_bars)
    eligible = np.isfinite(start_values) & np.isfinite(end_values)
    if not eligible.any():
        return None
    return float(np.mean(end_values[eligible] / start_values[eligible] - 1.0))


def benchmark_eligible_assets(prices: np.ndarray, start: int, end: int,
                              *, max_stale_bars: int = 5) -> int:
    """Count assets with both endpoint prices for a valid cross-sectional benchmark."""
    if end <= start or end >= prices.shape[1]:
        return 0
    start_values = _endpoint_values(prices, start, max_stale_bars=max_stale_bars)
    end_values = _endpoint_values(prices, end, max_stale_bars=max_stale_bars)
    eligible = np.isfinite(start_values) & np.isfinite(end_values)
    return int(np.sum(eligible))


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
    throttle = CpuBudgetThrottle()
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
        finally:
            throttle.pause()
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


def symbols_from_discovery_manifest(path: str) -> list[str]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload.get("candidates"), list):
        return [
            str(row["symbol"])
            for row in payload["candidates"]
            if row.get("status") == "READY_FOR_RESEARCH" and row.get("symbol")
        ]
    # The drawdown discovery manifest has already applied its frozen training
    # screen and records the symbols as candidate_symbols/selected. Preserve
    # that source-native selection instead of silently falling back to the
    # entire local store.
    if isinstance(payload.get("candidate_symbols"), list):
        return [str(symbol) for symbol in payload["candidate_symbols"] if str(symbol).strip()]
    return [
        str(row["symbol"])
        for row in payload.get("selected", [])
        if row.get("symbol")
    ]


def has_unresolved_price_jump(values: np.ndarray, maximum: float) -> bool:
    values = np.asarray(values, dtype=float)
    if len(values) < 300 or np.any(~np.isfinite(values)) or np.any(values <= 0):
        return True
    ratios = values[1:] / values[:-1]
    return bool(np.any(ratios > maximum) or np.any(ratios < 1.0 / maximum))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discovery-manifest", default=None,
                        help="only use READY_FOR_RESEARCH symbols from a discovery manifest")
    parser.add_argument("--output", default="data/cross_sectional_local_screen.json")
    parser.add_argument("--min-benchmark-assets", type=int, default=MIN_BENCHMARK_ASSETS,
                        help="minimum contemporaneous assets required for benchmark/OOS comparison")
    parser.add_argument("--max-benchmark-stale-bars", type=int, default=5,
                        help="bounded lookback rows for holiday/UTC-stale endpoint marks")
    args = parser.parse_args()
    as_of = datetime.now(UTC)
    manifest = run_manifest.pin("cross_sectional_local_screen", as_of=as_of,
                               params={"candidates": CANDIDATES, "risk_policies": RISK_POLICIES,
                                       "cost_bps": COST_BPS})
    report = {"generated_at": datetime.now(UTC).isoformat(), "as_of": as_of.isoformat(),
              "real_data_only": True, "research_only": True,
              "parameters": {"candidates": CANDIDATES, "risk_policies": RISK_POLICIES, "cost_bps": COST_BPS,
                              "oos_fraction": 0.3, "long_only": True,
                              "max_single_bar_multiple": MAX_MULTIPLE,
                              "min_benchmark_assets": args.min_benchmark_assets,
                              "max_benchmark_stale_bars": args.max_benchmark_stale_bars}, "domains": {}}
    all_symbols = (symbols_from_discovery_manifest(args.discovery_manifest)
                   if args.discovery_manifest else store.symbols(store.DAILY_BARS))
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
        benchmark_assets = benchmark_eligible_assets(
            matrix, cut, matrix.shape[1] - 1,
            max_stale_bars=args.max_benchmark_stale_bars,
        )
        if test_days < 20 or benchmark_assets < args.min_benchmark_assets:
            report["domains"][domain] = {
                "status": "blocked_insufficient_contemporaneous_universe",
                "symbols": len(used), "rejected_quality": rejected_quality,
                "test_days_with_four_assets": int(test_days),
                "benchmark_eligible_assets": benchmark_assets,
                "min_benchmark_assets": args.min_benchmark_assets,
            }
            continue
        rows = []
        for candidate in CANDIDATES:
            base_positions = select_long_only(matrix, **candidate)
            for risk_policy in RISK_POLICIES:
                positions = apply_risk_policy(matrix, base_positions, risk_policy)
                result = portfolio_result(matrix, positions, cut, COST_BPS[domain])
                train_result = portfolio_result(
                    matrix, positions, candidate["lookback"], COST_BPS[domain], end=cut
                )
                stress = portfolio_result(matrix, positions, cut, COST_BPS[domain], return_cap=0.20)
                folds = rolling_folds(matrix, positions, COST_BPS[domain])
                benchmark = equal_weight_benchmark(
                    matrix, cut, matrix.shape[1] - 1,
                    max_stale_bars=args.max_benchmark_stale_bars,
                )
                train_benchmark = equal_weight_benchmark(
                    matrix, candidate["lookback"], cut,
                    max_stale_bars=args.max_benchmark_stale_bars,
                )
                excess = result["oos_return"] - benchmark if benchmark is not None else None
                train_excess = (
                    train_result["oos_return"] - train_benchmark
                    if train_benchmark is not None and train_result["oos_return"] is not None else None
                )
                rows.append({**candidate, "risk_policy": risk_policy, **result, "benchmark_return": benchmark,
                         "train_return": train_result["oos_return"],
                         "train_benchmark_return": train_benchmark,
                         "train_excess_return": train_excess,
                         "excess_return": excess,
                         "stress_oos_return_cap_20pct": stress["oos_return"],
                         "rolling_folds": folds,
                         "rolling_median_excess": float(np.median([f["excess_return"] for f in folds])) if folds else None,
                         "status": "screen_only" if train_excess is not None and train_excess > 0 and
                         result["oos_return"] is not None and result["oos_return"] > 0 and
                         excess is not None and excess > 0 else "tested_no_edge"})
        eligible_rows = [row for row in rows if row.get("train_excess_return") is not None]
        selected = max(eligible_rows, key=lambda row: row["train_excess_return"]) if eligible_rows else None
        if selected is not None and selected["train_excess_return"] <= 0:
            selected = None
        report["domains"][domain] = {"status": "screened", "symbols": len(used),
                                     "rejected_quality": rejected_quality, "rows": rows,
                                     "selection": {
                                         "method": "max training excess only; OOS held out",
                                         "selected": selected,
                                         "status": "selected_on_training" if selected else "no_positive_training_edge",
                                     }}
    report["manifest"] = manifest.to_dict()
    out = Path(args.output)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    manifest.save(out)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    print(json.dumps(report["domains"], ensure_ascii=False, indent=2))
    print(f"写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
