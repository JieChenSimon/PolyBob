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
import os
import resource
import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import duckdb

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

from libs.data import data_lake, store
from libs.data.sec_insider import cluster_buys, fetch_insider_trades
from modules.simulation import SimulationService
from modules.simulation import metrics as sim_metrics
from modules.simulation.sources import SimSignal
from scripts.cross_sectional_local_screen import read_frames, symbol_domain
from scripts.crypto_tsmom_multifold_replay import MAJOR_CRYPTO, signed_positions
from scripts.insider_kernel_replay import QUARTERS, build_event_positions, filter_events_by_market_return


class CpuBudgetThrottle:
    """Bound this SQLite-heavy replay to a conservative CPU share."""

    def __init__(self, target: float = 0.50):
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
        if wall < 0.05 or cpu <= 0:
            return
        desired_wall = cpu / self.target
        if desired_wall > wall:
            time.sleep(min(desired_wall - wall, 2.0))
        self._wall = time.monotonic()
        self._cpu = self._cpu_seconds()


class MultiPositionSource:
    topics = ("features.snapshots",)

    def __init__(self, config: dict):
        self.positions = {str(symbol): [float(value) for value in values]
                          for symbol, values in config["positions_by_symbol"].items()}
        self.fractions = {str(symbol): float(value) for symbol, value in
                          config.get("position_fraction_by_instrument", {}).items()}
        self.index = defaultdict(int)
        self.previous = defaultdict(float)

    def advance_without_dispatch(self, symbol: str, index: int) -> None:
        """Advance a causal target through an unchanged flat interval.

        No market snapshot is needed when the instrument is flat and the target
        is unchanged; keeping this state transition explicit prevents the paper
        kernel from doing thousands of pointless SQLite dispatches.
        """
        values = self.positions.get(str(symbol), [])
        if 0 <= index < len(values):
            self.previous[str(symbol)] = values[index]
            self.index[str(symbol)] = index + 1

    def seek_to(self, symbol: str, index: int, previous: float) -> None:
        """Restore the causal cursor before a sparse mark/target dispatch."""
        self.previous[str(symbol)] = float(previous)
        self.index[str(symbol)] = int(index)

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
            signal_meta={"source": "multi_asset_portfolio_replay", "target": target,
                         # Cross-sectional research targets are weights, not just
                         # directions. Preserve that sizing in the real paper
                         # execution path instead of silently flattening every
                         # target to the same notional.
                         "position_fraction": abs(target) * self.fractions.get(symbol, 1.0)},
        )]


class ReplayClock:
    def __init__(self, value: datetime):
        self.current = value

    def __call__(self) -> datetime:
        return self.current


def write_progress(path: Path, *, status: str, completed: int, total: int,
                   latest_date: str | None = None) -> None:
    payload = {
        "status": status,
        "completed_dates": completed,
        "total_dates": total,
        "fraction": completed / total if total else 1.0,
        "latest_date": latest_date,
        "updated_at": datetime.now(UTC).isoformat(),
        "cpu_target": 0.50,
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


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


def _insider_leg(
    as_of: datetime,
    frames: dict[str, pd.Series],
    *,
    max_filing_delay_days: int | None = None,
    market_min_return: float = 0.0,
    market_max_return: float | None = None,
    hold_sessions: int = 20,
) -> tuple[dict[str, list[float]], set[str], int, int]:
    lake_path = data_lake.PART_ROOT / "sec_filings"
    events: list[tuple[str, str]] = []
    if lake_path.exists():
        # Aggregate inside DuckDB instead of materializing 80k tiny Parquet
        # files into pandas. This preserves same-day insider multiplicity while
        # keeping memory bounded and applying the PIT cutoff in the query.
        lake_glob = str(lake_path / "**" / "*.parquet")
        delay_clause = ""
        query_params: list[object] = [lake_glob, as_of]
        if max_filing_delay_days is not None:
            delay_clause = """
              AND datediff('day', try_cast(transaction_at AS DATE),
                           try_cast(event_at AS DATE)) BETWEEN 0 AND ?
            """
            query_params.append(int(max_filing_delay_days))
        query = f"""
            SELECT symbol, substr(event_at, 1, 10) AS event_date
            FROM read_parquet(?, union_by_name = true, hive_partitioning = true)
            WHERE is_open_market_buy = true
              AND value_usd >= 50000
              AND try_cast(observed_at AS TIMESTAMPTZ) <= ?
              {delay_clause}
            GROUP BY symbol, substr(event_at, 1, 10)
            HAVING count(*) >= 2
            ORDER BY symbol, event_date
        """
        with duckdb.connect() as connection:
            rows = connection.execute(query, query_params).fetchall()
        events = [(str(symbol), str(event_date)) for symbol, event_date in rows]
    if not events:
        # The bitemporal store is a valid fallback for a compact checkout, but
        # it may not retain same-day multiplicity and therefore cannot invent a
        # cluster when the lake query has no eligible events.
        stored_query = store.read(store.INSIDER_FILINGS, as_of=as_of)
    else:
        stored_query = pd.DataFrame()
    if stored_query.empty and not events:
        # A fresh checkout may not have materialized the official SEC dataset;
        # retain the real provider path as a fallback, but never synthesize it.
        throttle = CpuBudgetThrottle()
        trades = []
        for year, quarter in QUARTERS:
            trades.extend(fetch_insider_trades(year, quarter))
            throttle.pause()
        events = sorted(cluster_buys(trades, min_insiders=2, min_value_usd=50_000.0))
    elif not events:
        # Reuse the local PIT-normalized SEC lake. Re-parsing ZIP archives and
        # rewriting every normalized row on each replay was the dominant CPU and
        # disk cost, and did not add evidence once the source hash was stored.
        grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
        symbols_seen: set[str] = set()
        for row in stored_query.to_dict("records"):
            symbol = str(row.get("symbol") or "").upper()
            event_date = str(row.get("event_at") or row.get(store.EVENT_DATE) or "")[:10]
            value = float(row.get("value_usd") or 0.0)
            if not symbol or not event_date or not bool(row.get("is_open_market_buy")):
                continue
            symbols_seen.add(symbol)
            if value >= 50_000.0:
                grouped[(symbol, event_date)].append(value)
        events = sorted(key for key, values in grouped.items() if len(values) >= 2)
    symbols = sorted({symbol for symbol, _ in events})
    market = store.read(store.DAILY_BARS, "SPY", as_of=as_of).sort_values(store.EVENT_DATE)
    market_frame = pd.Series(
        market["close"].astype(float).to_numpy(),
        index=[str(value) for value in market[store.EVENT_DATE].tolist()], dtype=float,
    )
    events_before = len(events)
    events = filter_events_by_market_return(
        market_frame, events, lookback=20, min_return=market_min_return,
        max_return=market_max_return,
    )
    event_symbols = {symbol for symbol, _ in events}
    event_frames = {symbol: frames[symbol] for symbol in event_symbols if symbol in frames}
    positions = build_event_positions(event_frames, events, hold_sessions=hold_sessions)
    return positions, set(symbols), len(events), events_before


async def run(args: argparse.Namespace) -> dict:
    as_of = datetime.now(UTC)
    all_symbols = store.symbols(store.DAILY_BARS)
    crypto_symbols = [symbol for symbol in all_symbols if symbol_domain(symbol) == "crypto"]
    if args.crypto_major_only:
        crypto_symbols = [symbol for symbol in crypto_symbols if symbol in MAJOR_CRYPTO]
    crypto_frames, rejected_quality_count = read_frames(crypto_symbols, as_of)
    crypto_frames, crypto_stale_rejected = stable_daily_frames(crypto_frames, max_gap_days=4)
    if args.crypto_fraction <= 0:
        crypto_frames = {}
    if args.us_fraction <= 0:
        us_frames, us_stale_rejected = {}, []
        insider_positions, requested_us = {}, set()
        insider_events = insider_events_before = 0
    else:
        local_insider = store.read(store.INSIDER_FILINGS, as_of=as_of)
        if local_insider.empty:
            # Only the fallback path needs to acquire/parse the official SEC
            # bulk archives. Normal replays should never repeat that work.
            insider_symbols = sorted({
                trade.symbol for year, quarter in QUARTERS
                for trade in fetch_insider_trades(year, quarter)
            })
        else:
            insider_symbols = sorted({
                str(symbol).upper() for symbol in local_insider["symbol"].dropna().tolist()
            })
        us_frames = _series_frames(insider_symbols, as_of)
        us_frames, us_stale_rejected = stable_daily_frames(us_frames, max_gap_days=4)
        insider_positions, requested_us, insider_events, insider_events_before = _insider_leg(
            as_of, us_frames, max_filing_delay_days=args.us_max_filing_delay_days,
            market_min_return=args.us_market_min_return,
            market_max_return=args.us_market_max_return,
            hold_sessions=args.us_hold_sessions,
        )
        # Do not replay every symbol that merely has an SEC history. Only symbols
        # with a causal, market-filtered event can generate a target position.
        us_frames = {symbol: us_frames[symbol] for symbol in insider_positions
                     if symbol in us_frames}
    positions = dict(insider_positions)
    fractions = {symbol: args.us_fraction for symbol in us_frames}
    for symbol, series in crypto_frames.items():
        positions[symbol] = signed_positions(
            series.to_numpy(dtype=float), threshold=args.crypto_threshold,
        ).tolist()
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
    active_by_date: dict[str, list[tuple[str, pd.Series, int, float]]] = defaultdict(list)
    for symbol, series in frames.items():
        values = positions[symbol]
        for index, date in enumerate(series.index):
            previous = values[index - 1] if index else 0.0
            target = values[index]
            if target != 0.0 or previous != 0.0:
                active_by_date[str(date)].append((symbol, series, index, previous))
    final_by_date: dict[str, list[tuple[str, pd.Series, int, float, int]]] = defaultdict(list)
    for symbol, series in frames.items():
        last_index = len(series) - 1
        last_target = positions[symbol][last_index]
        if last_target != 0.0:
            final_by_date[str(series.index[-1])].append(
                (symbol, series, len(series), last_target, last_index)
            )
    clock = ReplayClock(datetime.fromisoformat(dates[0]).replace(tzinfo=UTC))
    out_dir = Path("data/.kernel_replay_multi_asset")
    out_dir.mkdir(parents=True, exist_ok=True)
    progress_path = Path(args.progress)
    write_progress(progress_path, status="running", completed=0, total=len(dates))
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
                "equity_interval_minutes": 1440.0,
                # Daily batch marks remain authoritative; scanning the entire
                # trade ledger after every fill is O(fills x ledger) and can
                # violate the workstation CPU budget on event-heavy dates.
                "record_equity_on_fill": False},
    )
    run_id = str(run["run_id"])
    await service.start_run(run_id)
    throttle = CpuBudgetThrottle()
    source = service._active[run_id].source
    for date_index, date in enumerate(dates, start=1):
        timestamp = datetime.fromisoformat(date).replace(tzinfo=UTC)
        for symbol_index, (symbol, series, index, previous_target) in enumerate(
                active_by_date.get(date, []), start=1):
            source.seek_to(symbol, index, previous_target)
            clock.current = timestamp
            await service._dispatch("features.snapshots", {
                "market_id": symbol, "timestamp": timestamp,
                "mid_price": float(series.to_numpy()[index]),
                "source": "local_daily_bars", "price_basis": "unadjusted",
            })
            if symbol_index % 5 == 0:
                throttle.pause()
        for symbol_index, (symbol, series, index, previous_target, price_index) in enumerate(
                final_by_date.get(date, []), start=1):
            source.seek_to(symbol, index, previous_target)
            await service._dispatch("features.snapshots", {
                "market_id": symbol, "timestamp": timestamp,
                "mid_price": float(series.to_numpy()[price_index]),
                "source": "local_daily_bars_final_liquidation",
                "price_basis": "unadjusted",
            })
            if symbol_index % 5 == 0:
                throttle.pause()
        await service._record_equity(service._active[run_id])
        throttle.pause()
        if date_index == 1 or date_index % 10 == 0 or date_index == len(dates):
            write_progress(progress_path, status="running", completed=date_index,
                           total=len(dates), latest_date=date)
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
        "legs": {"us_insider": {"events": insider_events,
                                  "events_before_filter": insider_events_before,
                                  "symbols_replayed": len(us_frames),
                                  "fraction": args.us_fraction,
                                  "hold_sessions": args.us_hold_sessions,
                                  "max_filing_delay_days": args.us_max_filing_delay_days,
                                  "market_min_return": args.us_market_min_return,
                                  "market_max_return": args.us_market_max_return},
                 "crypto_tsmom": {"symbols_replayed": len(crypto_frames),
                                   "quality_rejected_count": int(rejected_quality_count),
                                   "stale_rejected": crypto_stale_rejected,
                                   "fraction": args.crypto_fraction}},
        "execution_config": {"fee_bps": args.fee_bps, "mid_penalty_bps": args.mid_penalty_bps,
                              "allow_short": True, "crypto_threshold": args.crypto_threshold,
                              "crypto_major_only": args.crypto_major_only,
                              "us_hold_sessions": args.us_hold_sessions,
                              "us_max_filing_delay_days": args.us_max_filing_delay_days,
                              "us_market_min_return": args.us_market_min_return,
                              "us_market_max_return": args.us_market_max_return},
        "full_metrics": metrics, "risk_rejections": risk_rejections,
        "max_gross_exposure": max((float(point.gross_exposure) for point in points), default=0.0),
        "max_gross_leverage": max((float(point.gross_exposure) / point.equity
                                    for point in points if point.equity > 0), default=0.0),
        "calendar_period_pnl": dict(sorted(period_pnl.items())),
        "progress_path": str(progress_path),
        "status": "replay_only_not_promoted",
    }
    out = Path(args.output)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    write_progress(progress_path, status="completed", completed=len(dates),
                   total=len(dates), latest_date=dates[-1] if dates else None)
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
    parser.add_argument("--crypto-threshold", type=float, default=0.25)
    parser.add_argument("--crypto-major-only", action="store_true")
    parser.add_argument("--us-hold-sessions", type=int, default=20)
    parser.add_argument("--us-max-filing-delay-days", type=int, default=None)
    parser.add_argument("--us-market-min-return", type=float, default=0.0)
    parser.add_argument("--us-market-max-return", type=float, default=None)
    parser.add_argument("--fee-bps", type=float, default=20.0)
    parser.add_argument("--mid-penalty-bps", type=float, default=10.0)
    parser.add_argument("--output", default="data/multi_asset_portfolio_replay.json")
    parser.add_argument("--progress", default="data/multi_asset_portfolio_replay.progress.json")
    asyncio.run(run(parser.parse_args()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
