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
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from libs.data import store
from modules.simulation import SimulationService
from modules.simulation import metrics as sim_metrics
from scripts.cross_sectional_local_screen import symbol_domain, symbols_from_discovery_manifest
from scripts.cross_sectional_paper_replay import (
    _candidate_positions,
    filter_replay_dates,
)
from scripts.multi_asset_portfolio_replay import MultiPositionSource, ReplayClock


def binary_target(values: list[float]) -> list[float]:
    """Convert a portfolio weight signal into an isolated long-only target."""
    return [1.0 if float(value) > 0 else 0.0 for value in values]


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


async def _replay_one(
    symbol: str,
    series,
    targets: list[float],
    *,
    initial_capital: float,
    fee_bps: float,
    mid_penalty_bps: float,
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
            "position_fraction_by_instrument": {symbol: 1.0},
            "position_fraction": 0.0,
            "position_fraction_basis": "initial_capital",
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
        await service.stop_run(run_id)
        metrics = sim_metrics.compute_run_metrics(service.store, run_id)
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
    max_staleness_seconds = (14 if args.domain == "a_share" else 4) * 86400
    results = []
    for symbol in sorted(frames):
        # Signals are generated from the full cross-sectional history, but the
        # isolated account receives only this instrument's causal target stream.
        replay_series, replay_targets = slice_signal_window(
            frames[symbol], binary_target(positions[symbol]), args.start_date, args.end_date,
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
        },
        "data_quality": {
            "rejected_quality": rejected_quality,
            "rejected_stale": rejected_stale,
            "instrument_count": len(results),
        },
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
    parser.add_argument("--risk-policy", choices=("raw", "vol_target_10", "vol_target_10_dd"),
                        default="vol_target_10")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--initial-capital", type=float, default=100_000.0)
    parser.add_argument("--fee-bps", type=float, default=None)
    parser.add_argument("--mid-penalty-bps", type=float, default=10.0)
    parser.add_argument("--output", default="data/cross_sectional_standalone_replay.json")
    args = parser.parse_args()
    args.fee_bps = args.fee_bps if args.fee_bps is not None else (8.0 if args.domain == "a_share" else 5.0)
    asyncio.run(run(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
