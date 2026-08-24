"""Replay constrained US-insider and crypto momentum legs in one paper account.

This is a portfolio diagnostic, not a promotion command.  Every leg is built
from local real data, and all fills share one ``SimulationService`` account so
cash competition, fees, slippage, positions and equity are not double counted.
"""

from __future__ import annotations

import argparse
import asyncio
import bisect
import json
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from libs.data import store
from libs.data.sec_insider import cluster_buys, fetch_insider_trades
from modules.simulation import SimulationService
from modules.simulation import metrics as sim_metrics
from modules.simulation.sources import SimSignal
from scripts.cross_sectional_local_screen import read_frames, symbol_domain
from scripts.crypto_tsmom_multifold_replay import signed_positions
from scripts.insider_kernel_replay import QUARTERS, build_event_positions, filter_events_by_market_return


class MultiPositionSource:
    topics = ("features.snapshots",)

    def __init__(self, config: dict):
        self.positions = {str(symbol): [float(value) for value in values]
                          for symbol, values in config["positions_by_symbol"].items()}
        self.index = defaultdict(int)
        self.previous = defaultdict(float)

    async def on_snapshot(self, topic: str, snapshot: dict) -> list[SimSignal]:
        symbol = str(snapshot["market_id"])
        values = self.positions.get(symbol, [])
        index = self.index[symbol]
        if index >= len(values):
            return []
        target = values[index]
        self.index[symbol] += 1
        previous = self.previous[symbol]
        if target == previous:
            return []
        self.previous[symbol] = target
        side = "buy" if target > 0 or (target == 0 and previous < 0) else "sell"
        return [SimSignal(
            instrument_id=symbol, side=side, confidence=1.0,
            mid=float(snapshot["mid_price"]), timestamp=snapshot["timestamp"],
            signal_meta={"source": "multi_asset_portfolio_replay", "target": target},
        )]


class ReplayClock:
    def __init__(self, value: datetime):
        self.current = value

    def __call__(self) -> datetime:
        return self.current


def stable_daily_frames(frames: dict[str, pd.Series], max_gap_days: int = 4
                        ) -> tuple[dict[str, pd.Series], list[str]]:
    """Reject symbols whose local daily history has an unsafe calendar gap."""
    accepted = {}
    rejected = []
    for symbol, series in frames.items():
        dates = np.asarray(series.index.to_numpy(), dtype="datetime64[D]")
        gaps = np.diff(dates).astype("timedelta64[D]").astype(int)
        if len(gaps) and int(gaps.max()) > max_gap_days:
            rejected.append(symbol)
        else:
            accepted[symbol] = series
    return accepted, sorted(rejected)


def _series_frames(symbols: list[str], as_of: datetime) -> dict[str, pd.Series]:
    raw = store.read(store.DAILY_BARS, symbols, as_of=as_of)
    frames = {}
    for symbol, group in raw.groupby("symbol", sort=False):
        group = group.sort_values(store.EVENT_DATE)
        dates = [str(value) for value in group[store.EVENT_DATE].tolist()]
        close = group["close"].astype(float).to_numpy()
        if len(dates) >= 300 and np.all(np.isfinite(close)) and np.all(close > 0):
            frames[str(symbol)] = pd.Series(close, index=dates, dtype=float)
    return frames


def _insider_leg(as_of: datetime, frames: dict[str, pd.Series]) -> tuple[dict[str, list[float]], set[str], int, int]:
    trades = [trade for year, quarter in QUARTERS
              for trade in fetch_insider_trades(year, quarter)]
    events = sorted(cluster_buys(trades, min_insiders=2, min_value_usd=50_000.0))
    symbols = sorted({symbol for symbol, _ in events})
    market = store.read(store.DAILY_BARS, "SPY", as_of=as_of).sort_values(store.EVENT_DATE)
    market_frame = pd.Series(
        market["close"].astype(float).to_numpy(),
        index=[str(value) for value in market[store.EVENT_DATE].tolist()], dtype=float,
    )
    events_before = len(events)
    events = filter_events_by_market_return(market_frame, events, lookback=20, min_return=0.0)
    positions = build_event_positions(frames, events, hold_sessions=20)
    return positions, set(symbols), len(events), events_before


async def run(args: argparse.Namespace) -> dict:
    as_of = datetime.now(UTC)
    all_symbols = store.symbols(store.DAILY_BARS)
    crypto_symbols = [symbol for symbol in all_symbols if symbol_domain(symbol) == "crypto"]
    crypto_frames, rejected_quality_count = read_frames(crypto_symbols, as_of)
    crypto_frames, crypto_stale_rejected = stable_daily_frames(crypto_frames, max_gap_days=4)
    if args.crypto_fraction <= 0:
        crypto_frames = {}
    insider_symbols = sorted({
        trade.symbol for year, quarter in QUARTERS
        for trade in fetch_insider_trades(year, quarter)
    })
    us_frames = _series_frames(insider_symbols, as_of)
    us_frames, us_stale_rejected = stable_daily_frames(us_frames, max_gap_days=4)
    insider_positions, requested_us, insider_events, insider_events_before = _insider_leg(
        as_of, us_frames
    )
    positions = dict(insider_positions)
    fractions = {symbol: args.us_fraction for symbol in us_frames}
    for symbol, series in crypto_frames.items():
        positions[symbol] = signed_positions(series.to_numpy(dtype=float)).tolist()
        fractions[symbol] = args.crypto_fraction
    frames = {**us_frames, **crypto_frames}
    if len(frames) < 4:
        raise RuntimeError("insufficient multi-asset local coverage")
    # Histories end on different dates. Append a terminal zero target so each
    # instrument is liquidated on its own final observed bar; otherwise later
    # account snapshots would value that position with a stale mark.
    for symbol in frames:
        positions.setdefault(symbol, []).append(0.0)
    dates = sorted({date for series in frames.values() for date in series.index})
    clock = ReplayClock(datetime.fromisoformat(dates[0]).replace(tzinfo=UTC))
    out_dir = Path("data/.kernel_replay_multi_asset")
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / f"multi-{uuid.uuid4().hex[:10]}.sqlite3"
    service = SimulationService(
        db_path, clock=clock, equity_poll_seconds=10**9,
        source_factories={"multi_positions": lambda config, _db: MultiPositionSource(config)},
    )
    await service.start()
    run = await service.create_run(
        name="multi-asset-portfolio-replay", strategy_id="multi_positions",
        universe=list(frames), initial_capital=100_000.0,
        config={"positions_by_symbol": positions, "position_fraction": 0.0,
                "position_fraction_by_instrument": fractions, "fee_bps": args.fee_bps,
                "mid_penalty_bps": args.mid_penalty_bps, "allow_short": True,
                "cooldown_seconds": 0.0, "max_staleness_seconds": 345600.0,
                "equity_interval_minutes": 1440.0},
    )
    run_id = str(run["run_id"])
    await service.start_run(run_id)
    for date in dates:
        timestamp = datetime.fromisoformat(date).replace(tzinfo=UTC)
        for symbol, series in frames.items():
            if date not in series.index:
                continue
            index = series.index.get_loc(date)
            clock.current = timestamp
            await service._dispatch("features.snapshots", {
                "market_id": symbol, "timestamp": timestamp,
                "mid_price": float(series.to_numpy()[index]),
                "source": "local_daily_bars", "price_basis": "unadjusted",
            })
        for symbol, series in frames.items():
            if date != series.index[-1]:
                continue
            index = series.index.get_loc(date)
            await service._dispatch("features.snapshots", {
                "market_id": symbol, "timestamp": timestamp,
                "mid_price": float(series.to_numpy()[index]),
                "source": "local_daily_bars_final_liquidation",
                "price_basis": "unadjusted",
            })
        await service._record_equity(service._active[run_id])
    active = service._active.get(run_id)
    risk_rejections = int(active.risk_rejections) if active is not None else None
    await service.stop_run(run_id)
    metrics = sim_metrics.compute_run_metrics(service.store, run_id)
    points = service.store.list_equity_points(run_id)
    trades = service.store.list_trades(run_id)
    period_pnl: dict[str, float] = defaultdict(float)
    for trade in trades:
        if trade.realized_pnl is None:
            continue
        executed = trade.executed_at
        if isinstance(executed, str):
            executed = datetime.fromisoformat(executed.replace("Z", "+00:00"))
        period = f"{executed.year}-Q{(executed.month - 1) // 3 + 1}"
        period_pnl[period] += float(trade.realized_pnl)
    report = {
        "generated_at": datetime.now(UTC).isoformat(), "real_data_only": True,
        "execution_kernel": "modules.simulation.SimulationService",
        "sec_quarters": QUARTERS,
        "data_quality": {"daily_max_gap_days": 4,
                          "us_stale_rejected": us_stale_rejected,
                          "crypto_stale_rejected": crypto_stale_rejected,
                          "crypto_quality_rejected_count": int(rejected_quality_count)},
        "legs": {"us_insider_market20": {"events": insider_events,
                                           "events_before_filter": insider_events_before,
                                           "symbols_replayed": len(us_frames),
                                           "fraction": args.us_fraction},
                 "crypto_tsmom": {"symbols_replayed": len(crypto_frames),
                                   "quality_rejected_count": int(rejected_quality_count),
                                   "stale_rejected": crypto_stale_rejected,
                                   "fraction": args.crypto_fraction}},
        "execution_config": {"fee_bps": args.fee_bps, "mid_penalty_bps": args.mid_penalty_bps,
                              "allow_short": True},
        "full_metrics": metrics, "risk_rejections": risk_rejections,
        "max_gross_exposure": max((float(point.gross_exposure) for point in points), default=0.0),
        "max_gross_leverage": max((float(point.gross_exposure) / point.equity
                                    for point in points if point.equity > 0), default=0.0),
        "calendar_period_pnl": dict(sorted(period_pnl.items())),
        "status": "replay_only_not_promoted",
    }
    out = Path(args.output)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    await service.stop()
    for suffix in ("", "-wal", "-shm"):
        db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)
    print(json.dumps({key: value for key, value in report.items() if key != "full_metrics"},
                     ensure_ascii=False, indent=2, default=str))
    print(f"写入 {out}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--us-fraction", type=float, default=0.0014)
    parser.add_argument("--crypto-fraction", type=float, default=0.0)
    parser.add_argument("--fee-bps", type=float, default=20.0)
    parser.add_argument("--mid-penalty-bps", type=float, default=10.0)
    parser.add_argument("--output", default="data/multi_asset_portfolio_replay.json")
    asyncio.run(run(parser.parse_args()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
