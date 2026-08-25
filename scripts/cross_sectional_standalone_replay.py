"""Replay one pre-registered cross-sectional signal independently per instrument.

The portfolio replay intentionally measures shared-account contribution.  This
runner uses the same signal history and the same SimulationService kernel, but
gives each instrument its own fixed initial capital and a binary target: fully
invested when the cross-sectional signal selects it, otherwise flat.  That makes
per-instrument return targets measurable without dividing a shared PnL by an
arbitrary denominator.  It remains research-only until executable quote evidence
and the other promotion gates pass.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

import numpy as np

from libs.data import store
from modules.simulation import SimulationService
from modules.simulation import metrics as sim_metrics
from scripts.cross_sectional_local_screen import symbol_domain, symbols_from_discovery_manifest
from scripts.cross_sectional_paper_replay import (
    _candidate_positions,
    filter_replay_dates,
)
from scripts.multi_asset_portfolio_replay import MultiPositionSource, ReplayClock


def execution_safe_fraction(fee_bps: float, mid_penalty_bps: float,
                            cash_buffer_fraction: float = 0.001) -> float:
    """Return a cash-safe target fraction for a full-fill diagnostic.

    A nominal 100% target is not executable when the first buy also pays the
    modeled mid penalty and taker fee.  Keep a small explicit cash buffer so a
    loss does not turn the next valid re-entry into a cash-solvency rejection.
    The account still reports returns against its fixed initial-capital
    denominator; the position sizing basis itself is current equity.
    """
    if fee_bps < 0 or mid_penalty_bps < 0:
        raise ValueError("execution costs must be non-negative")
    if not 0 <= cash_buffer_fraction < 1:
        raise ValueError("cash_buffer_fraction must be in [0, 1)")
    fee_factor = 1.0 + float(fee_bps) / 10_000.0
    penalty_factor = 1.0 + float(mid_penalty_bps) / 10_000.0
    return (1.0 - cash_buffer_fraction) / (fee_factor * penalty_factor)


def _sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def data_snapshot_digest(frames: dict[str, object], manifest_path: str | None = None) -> dict:
    """Create a deterministic, compact identity for the replay input.

    The digest covers the actual aligned per-symbol date/value series consumed
    by the isolated replay, not merely the source directory mtime. This makes
    silent local refreshes visible when two strategy reports are compared.
    """
    digest = hashlib.sha256()
    symbols: list[dict] = []
    for symbol in sorted(frames):
        series = frames[symbol]
        rows = [(str(index), float(value)) for index, value in series.items()]
        for event_date, close in rows:
            digest.update(f"{symbol}\t{event_date}\t{close:.17g}\n".encode("utf-8"))
        symbols.append({
            "symbol": symbol,
            "rows": len(rows),
            "start": rows[0][0] if rows else None,
            "end": rows[-1][0] if rows else None,
        })
    return {
        "schema_version": "cross-sectional-replay-input-v1",
        "sha256": digest.hexdigest(),
        "manifest_path": manifest_path,
        "manifest_sha256": _sha256_file(Path(manifest_path)) if manifest_path else None,
        "symbols": symbols,
    }


def binary_target(values: list[float]) -> list[float]:
    """Convert a portfolio weight signal into an isolated long-only target."""
    return [1.0 if float(value) > 0 else 0.0 for value in values]


def apply_tail_risk_guard(
    series,
    targets: list[float],
    *,
    stop_loss_pct: float | None = None,
    trailing_drawdown_pct: float | None = None,
    cooldown_bars: int = 0,
    max_annualized_vol: float | None = None,
    volatility_window: int = 20,
) -> list[float]:
    """Apply causal per-instrument loss and volatility guards to targets.

    Decisions at bar ``i`` use the current bar and returns strictly before it.
    A guard can flatten a selected position, but never creates a long position
    that the original signal did not request.  ``None`` disables each guard.
    """
    prices = np.asarray(series.to_numpy(dtype=float), dtype=float)
    if len(targets) < len(prices):
        raise ValueError("targets must cover every price bar")
    if stop_loss_pct is not None and not 0 < stop_loss_pct < 1:
        raise ValueError("stop_loss_pct must be between 0 and 1")
    if trailing_drawdown_pct is not None and not 0 < trailing_drawdown_pct < 1:
        raise ValueError("trailing_drawdown_pct must be between 0 and 1")
    if max_annualized_vol is not None and max_annualized_vol <= 0:
        raise ValueError("max_annualized_vol must be positive")
    guarded: list[float] = []
    held = False
    entry = None
    peak = None
    cooldown = 0
    for index, price in enumerate(prices):
        desired = float(targets[index]) > 0
        previous_returns = prices[max(0, index - volatility_window):index + 1]
        valid_returns = previous_returns[:-1] > 0
        if len(previous_returns) >= 2:
            returns = previous_returns[1:][valid_returns] / previous_returns[:-1][valid_returns] - 1.0
            annualized_vol = float(np.std(returns, ddof=1) * np.sqrt(252.0)) if len(returns) >= 2 else 0.0
        else:
            annualized_vol = 0.0
        volatility_block = (
            max_annualized_vol is not None
            and annualized_vol > max_annualized_vol
        )
        should_exit = False
        if held and price > 0 and entry is not None and peak is not None:
            peak = max(peak, float(price))
            if stop_loss_pct is not None and price <= entry * (1.0 - stop_loss_pct):
                should_exit = True
            if trailing_drawdown_pct is not None and price <= peak * (1.0 - trailing_drawdown_pct):
                should_exit = True
            if volatility_block:
                should_exit = True
        exited_this_bar = False
        if held and (not desired or should_exit):
            held = False
            entry = None
            peak = None
            cooldown = max(0, int(cooldown_bars)) if should_exit else 0
            exited_this_bar = True
        if exited_this_bar:
            guarded.append(0.0)
            continue
        if not held and cooldown > 0:
            cooldown -= 1
            guarded.append(0.0)
            continue
        if not held and desired and not volatility_block and price > 0:
            held = True
            entry = float(price)
            peak = float(price)
        guarded.append(1.0 if held else 0.0)
    return guarded + [0.0]


def slice_signal_window(series, targets: list[float], start_date: str | None,
                        end_date: str | None):
    """Slice bars and their causal targets to the inclusive replay window."""
    dates = [str(value)[:10] for value in series.index]
    indices = [index for index, date in enumerate(dates)
               if (start_date is None or date >= start_date)
               and (end_date is None or date <= end_date)]
    sliced = series.iloc[indices]
    sliced_targets = [float(targets[index]) for index in indices]
    return sliced, sliced_targets + [0.0]


def rolling_equity_folds(points, fold_count: int = 3) -> dict:
    """Summarize contiguous equity folds without selecting on their returns.

    Fold boundaries are determined only by chronological observation count.  The
    result is a stability diagnostic: it does not replace the independent OOS
    gate, but exposes whether a total return is concentrated in one interval.
    """
    def field(point, name: str):
        return getattr(point, name) if hasattr(point, name) else point[name]

    ordered = sorted(points, key=lambda point: str(field(point, "ts")))
    if fold_count < 2 or len(ordered) < fold_count * 2:
        return {"status": "UNKNOWN", "reason": "insufficient_equity_points", "folds": []}
    boundaries = [round(index * len(ordered) / fold_count) for index in range(fold_count + 1)]
    folds = []
    for index in range(fold_count):
        chunk = ordered[boundaries[index]:boundaries[index + 1]]
        if len(chunk) < 2:
            continue
        values = [float(field(point, "equity")) for point in chunk]
        start, end = values[0], values[-1]
        peak = start
        max_drawdown = 0.0
        for value in values:
            peak = max(peak, value)
            if peak > 0:
                max_drawdown = max(max_drawdown, (peak - value) / peak)
        folds.append({
            "index": index + 1,
            "start": str(field(chunk[0], "ts"))[:10],
            "end": str(field(chunk[-1], "ts"))[:10],
            "observations": len(chunk),
            "return": end / start - 1.0 if start > 0 else None,
            "max_drawdown": max_drawdown,
        })
    returns = [fold["return"] for fold in folds if fold["return"] is not None]
    positive = sum(value > 0 for value in returns)
    status = (
        "PASS_STABLE"
        if len(returns) == fold_count and positive >= max(2, fold_count - 1)
        else "FAIL_UNSTABLE"
    )
    return {
        "status": status,
        "fold_count": len(folds),
        "positive_fold_count": positive,
        "median_fold_return": median(returns) if returns else None,
        "folds": folds,
    }


async def _replay_one(
    symbol: str,
    series,
    targets: list[float],
    *,
    initial_capital: float,
    fee_bps: float,
    mid_penalty_bps: float,
    position_fraction: float,
    max_staleness_seconds: float,
    output_dir: Path,
) -> dict:
    dates = [str(value) for value in series.index]
    if not dates:
        return {"symbol": symbol, "status": "UNKNOWN_NO_DATA"}
    clock = ReplayClock(datetime.fromisoformat(dates[0]).replace(tzinfo=UTC))
    db_path = output_dir / f"{symbol}-{uuid.uuid4().hex[:8]}.sqlite3"
    service = SimulationService(
        db_path,
        clock=clock,
        equity_poll_seconds=10**9,
        source_factories={"multi_positions": lambda config, _db: MultiPositionSource(config)},
    )
    await service.start()
    run = await service.create_run(
        name=f"cross-sectional-standalone:{symbol}",
        strategy_id="multi_positions",
        universe=[symbol],
        initial_capital=initial_capital,
        config={
            "positions_by_symbol": {symbol: targets},
            "position_fraction_by_instrument": {symbol: position_fraction},
            "position_fraction": 0.0,
            "position_fraction_basis": "equity",
            "fee_bps": fee_bps,
            "mid_penalty_bps": mid_penalty_bps,
            "allow_short": False,
            "cooldown_seconds": 0.0,
            "max_staleness_seconds": max_staleness_seconds,
            "equity_interval_minutes": 1440.0,
        },
    )
    run_id = str(run["run_id"])
    await service.start_run(run_id)
    try:
        for date, price in zip(dates, series.to_numpy(dtype=float), strict=True):
            timestamp = datetime.fromisoformat(date).replace(tzinfo=UTC)
            clock.current = timestamp
            await service._dispatch("features.snapshots", {
                "market_id": symbol,
                "timestamp": timestamp,
                "mid_price": float(price),
                "source": "local_daily_bars",
                "price_basis": "provider_declared",
            })
            await service._record_equity(service._active[run_id])
        # The final target is zero, so the last observed bar is also the
        # liquidation mark rather than an open position carried beyond OOS.
        timestamp = datetime.fromisoformat(dates[-1]).replace(tzinfo=UTC)
        clock.current = timestamp
        await service._dispatch("features.snapshots", {
            "market_id": symbol,
            "timestamp": timestamp,
            "mid_price": float(series.iloc[-1]),
            "source": "local_daily_bars_final_liquidation",
            "price_basis": "provider_declared",
        })
        await service._record_equity(service._active[run_id])
        active = service._active.get(run_id)
        risk_rejections = int(active.risk_rejections) if active is not None else None
        await service.stop_run(run_id)
        metrics = sim_metrics.compute_run_metrics(service.store, run_id)
        stability = rolling_equity_folds(service.store.list_equity_points(run_id))
        evidence = metrics.get("execution_evidence", {})
        return {
            "symbol": symbol,
            "domain": symbol_domain(symbol),
            "status": "ANALYZED",
            "initial_capital": initial_capital,
            "bars": len(dates),
            "start": dates[0][:10],
            "end": dates[-1][:10],
            "metrics": metrics,
            "return_target": metrics.get("return_target"),
            "stability": stability,
            "risk_rejections": risk_rejections,
            "execution_evidence": evidence,
            "promotion": "BLOCKED",
            "promotion_reason": "historical_executable_quote_unknown",
        }
    finally:
        await service.stop()
        for suffix in ("", "-wal", "-shm"):
            db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)


async def run(args: argparse.Namespace) -> dict:
    as_of = datetime.now(UTC)
    requested = (
        symbols_from_discovery_manifest(args.discovery_manifest)
        if args.discovery_manifest else store.symbols(store.DAILY_BARS)
    )
    requested = [s for s in requested if symbol_domain(s) == args.domain]
    frames, positions, dates, rejected_quality, rejected_stale = _candidate_positions(
        requested, as_of, args.lookback, args.top_frac, args.rebalance_days, args.risk_policy,
    )
    dates = filter_replay_dates(dates, args.start_date, args.end_date)
    if not dates:
        raise RuntimeError("requested replay window has no dates")
    output_dir = Path(args.output).parent / f".standalone-{uuid.uuid4().hex[:8]}"
    output_dir.mkdir(parents=True, exist_ok=True)
    position_fraction = execution_safe_fraction(args.fee_bps, args.mid_penalty_bps)
    max_staleness_seconds = (14 if args.domain == "a_share" else 4) * 86400
    results = []
    for symbol in sorted(frames):
        # Signals are generated from the full cross-sectional history, but the
        # isolated account receives only this instrument's causal target stream.
        full_targets = apply_tail_risk_guard(
            frames[symbol],
            binary_target(positions[symbol]),
            stop_loss_pct=args.stop_loss_pct,
            trailing_drawdown_pct=args.trailing_drawdown_pct,
            cooldown_bars=args.cooldown_bars,
            max_annualized_vol=args.max_annualized_vol,
        )
        replay_series, replay_targets = slice_signal_window(
            frames[symbol], full_targets, args.start_date, args.end_date,
        )
        if replay_series.empty:
            continue
        result = await _replay_one(
            symbol,
            replay_series,
            replay_targets,
            initial_capital=args.initial_capital,
            fee_bps=args.fee_bps,
            mid_penalty_bps=args.mid_penalty_bps,
            position_fraction=position_fraction,
            max_staleness_seconds=max_staleness_seconds,
            output_dir=output_dir,
        )
        results.append(result)
    report = {
        "schema_version": "cross-sectional-standalone-replay-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "real_data_only": True,
        "research_only": True,
        "execution_kernel": "modules.simulation.SimulationService",
        "domain": args.domain,
        "signal_contract": {
            "lookback": args.lookback,
            "top_frac": args.top_frac,
            "rebalance_days": args.rebalance_days,
            "risk_policy": args.risk_policy,
            "selection_basis": "pre_registered_cross_sectional_signal",
            "isolated_target": "binary_full_capital_when_selected",
            "tail_risk_guard": {
                "stop_loss_pct": args.stop_loss_pct,
                "trailing_drawdown_pct": args.trailing_drawdown_pct,
                "cooldown_bars": args.cooldown_bars,
                "max_annualized_vol": args.max_annualized_vol,
                "volatility_window": 20,
            },
        },
        "replay_window": {
            "requested_start": args.start_date,
            "requested_end": args.end_date,
            "actual_start": dates[0],
            "actual_end": dates[-1],
        },
        "capital_contract": {
            "initial_capital_per_instrument": args.initial_capital,
            "denominator": "fixed_initial_capital_per_instrument",
            "position_fraction_basis": "equity",
            "execution_safe_fraction": position_fraction,
            "cash_buffer_fraction": 0.001,
        },
        "data_quality": {
            "rejected_quality": rejected_quality,
            "rejected_stale": rejected_stale,
            "instrument_count": len(results),
        },
        "data_snapshot": data_snapshot_digest(frames, args.discovery_manifest),
        "results": results,
        "promotion": {
            "status": "BLOCKED",
            "reason": "historical_executable_quote_unknown_and_research_gates_incomplete",
        },
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    for path in output_dir.glob("*"):
        path.unlink(missing_ok=True)
    output_dir.rmdir()
    print(json.dumps({
        "domain": args.domain,
        "instruments": len(results),
        "status": report["promotion"]["status"],
        "output": str(out),
    }, ensure_ascii=False))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", choices=("a_share", "us_equity"), required=True)
    parser.add_argument("--discovery-manifest", default=None,
                        help="only use READY_FOR_RESEARCH symbols from a discovery manifest")
    parser.add_argument("--lookback", type=int, default=60)
    parser.add_argument("--top-frac", type=float, default=0.2)
    parser.add_argument("--rebalance-days", type=int, default=10)
    parser.add_argument("--risk-policy", choices=("raw", "vol_target_10", "vol_target_10_dd",
                                                   "vol_target_10_dd_recovery"),
                        default="vol_target_10")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--initial-capital", type=float, default=100_000.0)
    parser.add_argument("--fee-bps", type=float, default=None)
    parser.add_argument("--mid-penalty-bps", type=float, default=10.0)
    parser.add_argument("--stop-loss-pct", type=float, default=None)
    parser.add_argument("--trailing-drawdown-pct", type=float, default=None)
    parser.add_argument("--cooldown-bars", type=int, default=0)
    parser.add_argument("--max-annualized-vol", type=float, default=None)
    parser.add_argument("--output", default="data/cross_sectional_standalone_replay.json")
    args = parser.parse_args()
    args.fee_bps = args.fee_bps if args.fee_bps is not None else (8.0 if args.domain == "a_share" else 5.0)
    asyncio.run(run(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
