"""Replay one pre-registered cross-sectional candidate through Paper Lab."""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from libs.data import store
from modules.simulation import SimulationService
from modules.simulation import metrics as sim_metrics
from scripts.cross_sectional_local_screen import (
    align_frames,
    apply_risk_policy,
    read_frames,
    symbols_from_discovery_manifest,
    select_long_only,
    symbol_domain,
)
from scripts.multi_asset_portfolio_replay import MultiPositionSource, ReplayClock, stable_daily_frames


def filter_replay_dates(dates: list[str], start_date: str | None = None,
                        end_date: str | None = None) -> list[str]:
    """Filter an inclusive replay window without changing signal history."""
    return [date for date in dates
            if (start_date is None or date >= start_date)
            and (end_date is None or date <= end_date)]


def summarize_instrument_oos_pnl(
    points: list[dict], *, start_date: str, end_date: str,
) -> dict[str, dict]:
    """Summarize per-instrument OOS contribution without inventing returns.

    Instrument PnL points are contributions to the shared account.  Unless a
    fixed per-instrument capital denominator is supplied, they are not
    standalone percentage returns and cannot pass the user's annual/monthly
    target gate.
    """
    grouped: dict[str, list[dict]] = {}
    for point in points:
        instrument = str(point.get("instrument_id", ""))
        ts = str(point.get("ts", ""))[:10]
        if instrument and start_date <= ts <= end_date:
            grouped.setdefault(instrument, []).append(point)
    result: dict[str, dict] = {}
    for instrument, values in grouped.items():
        values.sort(key=lambda item: str(item.get("ts", "")))
        first = float(values[0].get("pnl", 0.0))
        last = float(values[-1].get("pnl", 0.0))
        result[instrument] = {
            "oos_start": str(values[0].get("ts")),
            "oos_end": str(values[-1].get("ts")),
            "pnl_contribution": last - first,
            "latest_cumulative_pnl": last,
            "point_count": len(values),
            "degraded": any(bool(item.get("degraded")) for item in values),
            "standalone_return": None,
            "return_target_status": "UNKNOWN",
            "return_target_reason": "no_fixed_per_instrument_capital_denominator",
        }
    return result


def execution_evidence_status(metrics: dict) -> dict[str, object]:
    """Classify whether replay fills have executable quote evidence.

    A daily midpoint replay can be useful for signal diagnostics, but it is not
    equivalent to a historical order-book replay.  Keep this classification
    explicit and fail closed when any trade lacks depth or a quote observation.
    """
    trades = int(metrics.get("trade_count", 0) or 0)
    full_depth = int(metrics.get("full_depth_trade_count", 0) or 0)
    missing_depth = int(metrics.get("missing_depth_trade_count", 0) or 0)
    observations = int(metrics.get("quote_observation_count", 0) or 0)
    linked = int(metrics.get("trade_quote_observation_link_count", 0) or 0)
    if trades == 0:
        status = "UNKNOWN_NO_TRADES"
    elif full_depth == trades and observations >= trades and linked == trades:
        status = "FULL_DEPTH_EXECUTABLE_EVIDENCE"
    elif missing_depth or full_depth < trades or observations < trades or linked < trades:
        status = "UNKNOWN_NO_EXECUTABLE_DEPTH"
    else:
        status = "UNKNOWN_PARTIAL_EXECUTABLE_EVIDENCE"
    return {
        "status": status,
        "trade_count": trades,
        "full_depth_trade_count": full_depth,
        "missing_depth_trade_count": missing_depth,
        "quote_observation_count": observations,
        "trade_quote_observation_link_count": linked,
        "promotion_allowed": status == "FULL_DEPTH_EXECUTABLE_EVIDENCE",
    }


def _candidate_positions(symbols: list[str], as_of: datetime, lookback: int,
                         top_frac: float, rebalance_days: int, risk_policy: str):
    frames, rejected_quality = read_frames(symbols, as_of)
    # Calendar gaps are domain-specific: weekends are at most three calendar
    # days, while A-share public holidays can create a longer legitimate gap.
    # This is still a bounded data-quality gate, not an interpolation rule.
    frames, rejected_stale = stable_daily_frames(
        frames, max_gap_days=14 if symbols and symbol_domain(symbols[0]) == "a_share" else 4
    )
    if len(frames) < 4:
        raise RuntimeError(f"insufficient stable symbols: {len(frames)}")
    aligned = align_frames(frames)
    matrix = aligned.to_numpy(dtype=float).T
    base = select_long_only(matrix, lookback, top_frac, rebalance_days)
    positions = apply_risk_policy(matrix, base, risk_policy)
    by_symbol: dict[str, list[float]] = {}
    for index, symbol in enumerate(aligned.columns):
        local_indices = aligned.index.get_indexer(frames[symbol].index)
        by_symbol[symbol] = positions[index, local_indices].tolist() + [0.0]
    dates = sorted({date for series in frames.values() for date in series.index})
    return frames, by_symbol, dates, rejected_quality, rejected_stale


async def run(args: argparse.Namespace) -> dict:
    as_of = datetime.now(UTC)
    requested = symbols_from_discovery_manifest(args.discovery_manifest)
    symbols = [symbol for symbol in requested if symbol_domain(symbol) == args.domain]
    frames, positions, dates, rejected_quality, rejected_stale = _candidate_positions(
        symbols, as_of, args.lookback, args.top_frac, args.rebalance_days, args.risk_policy
    )
    dates = filter_replay_dates(dates, args.start_date, args.end_date)
    if not dates:
        raise RuntimeError("requested replay window has no dates")
    clock = ReplayClock(datetime.fromisoformat(dates[0]).replace(tzinfo=UTC))
    db_path = Path(args.output).with_suffix(f".{uuid.uuid4().hex[:8]}.sqlite3")
    service = SimulationService(
        db_path, clock=clock, equity_poll_seconds=10**9,
        source_factories={"multi_positions": lambda config, _db: MultiPositionSource(config)},
    )
    await service.start()
    fractions = {symbol: 1.0 for symbol in frames}
    max_staleness_seconds = (14 if args.domain == "a_share" else 4) * 86400
    run = await service.create_run(
        name=f"cross-sectional-paper:{args.domain}", strategy_id="multi_positions",
        universe=list(frames), initial_capital=100_000.0,
        config={"positions_by_symbol": positions,
                "position_fraction_by_instrument": fractions,
                "position_fraction": 0.0, "fee_bps": args.fee_bps,
                "mid_penalty_bps": args.mid_penalty_bps, "allow_short": False,
                "cooldown_seconds": 0.0, "max_staleness_seconds": float(max_staleness_seconds),
                "equity_interval_minutes": 1440.0},
    )
    run_id = str(run["run_id"])
    await service.start_run(run_id)
    for date in dates:
        timestamp = datetime.fromisoformat(date).replace(tzinfo=UTC)
        clock.current = timestamp
        for symbol, series in frames.items():
            if date not in series.index:
                continue
            index = series.index.get_loc(date)
            await service._dispatch("features.snapshots", {
                "market_id": symbol, "timestamp": timestamp,
                "mid_price": float(series.to_numpy()[index]),
                "source": "local_daily_bars", "price_basis": "provider_declared",
            })
        # The position stream has one terminal zero after each symbol's last
        # bar. Emit a second snapshot on that same final observation so the
        # paper broker actually receives the liquidation target and the final
        # equity point is not degraded by a stale open position.
        for symbol, series in frames.items():
            if date != series.index[-1]:
                continue
            index = series.index.get_loc(date)
            await service._dispatch("features.snapshots", {
                "market_id": symbol, "timestamp": timestamp,
                "mid_price": float(series.to_numpy()[index]),
                "source": "local_daily_bars_final_liquidation",
                "price_basis": "provider_declared",
            })
    active = service._active.get(run_id)
    risk_rejections = int(active.risk_rejections) if active is not None else None
    await service.stop_run(run_id)
    metrics = sim_metrics.compute_run_metrics(service.store, run_id)
    instrument_oos_evidence = summarize_instrument_oos_pnl(
        metrics.get("instrument_pnl_curve", []),
        start_date=dates[0], end_date=dates[-1],
    )
    execution_evidence = execution_evidence_status(metrics)
    report = {
        "generated_at": datetime.now(UTC).isoformat(), "real_data_only": True,
        "execution_kernel": "modules.simulation.SimulationService",
        "domain": args.domain, "symbols": sorted(frames),
        "candidate": {"lookback": args.lookback, "top_frac": args.top_frac,
                       "rebalance_days": args.rebalance_days,
                       "risk_policy": args.risk_policy},
        "replay_window": {"start_date": args.start_date, "end_date": args.end_date,
                           "actual_start": dates[0], "actual_end": dates[-1]},
        "data_quality": {"rejected_quality": rejected_quality,
                          "rejected_stale": rejected_stale},
        "execution_config": {"fee_bps": args.fee_bps,
                              "mid_penalty_bps": args.mid_penalty_bps,
                              "allow_short": False},
        "metrics": metrics, "risk_rejections": risk_rejections,
        "instrument_oos_evidence": instrument_oos_evidence,
        "execution_evidence": execution_evidence,
        "status": "replay_only_not_promoted",
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    await service.stop()
    for suffix in ("", "-wal", "-shm"):
        db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)
    print(json.dumps({"domain": args.domain, "symbols": len(frames),
                      "metrics": metrics, "status": report["status"]}, ensure_ascii=False))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", choices=("a_share", "us_equity"), required=True)
    parser.add_argument("--discovery-manifest", default="data/discovered_equity_universe.json")
    parser.add_argument("--lookback", type=int, default=20)
    parser.add_argument("--top-frac", type=float, default=0.2)
    parser.add_argument("--rebalance-days", type=int, default=10)
    parser.add_argument("--risk-policy", choices=("raw", "vol_target_10", "vol_target_10_dd"),
                        default="vol_target_10")
    parser.add_argument("--start-date", default=None,
                        help="inclusive YYYY-MM-DD replay start; signals still use prior history")
    parser.add_argument("--end-date", default=None,
                        help="inclusive YYYY-MM-DD replay end")
    parser.add_argument("--fee-bps", type=float, default=None)
    parser.add_argument("--mid-penalty-bps", type=float, default=10.0)
    parser.add_argument("--output", default="data/cross_sectional_paper_replay.json")
    args = parser.parse_args()
    args.fee_bps = args.fee_bps if args.fee_bps is not None else (8.0 if args.domain == "a_share" else 5.0)
    asyncio.run(run(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
