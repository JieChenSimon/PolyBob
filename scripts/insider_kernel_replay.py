"""Replay SEC insider-cluster events through the real Paper Lab kernel.

The event study and this replay deliberately answer different questions.  The
event study measures cross-sectional excess returns; this script uses the
public filing date, enters on the next local trading bar, exits after a fixed
number of sessions, and books the actual Paper Lab fee and mid-price penalty.
It is evidence only and never grants promotion authority.
"""

from __future__ import annotations

import asyncio
import argparse
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

QUARTERS = [(year, quarter) for year in (2021, 2022, 2023, 2024, 2025, 2026)
            for quarter in (1, 2, 3, 4)
            if (2021, 3) <= (year, quarter) <= (2026, 2)]
HOLD_SESSIONS = 5
MIN_INSIDERS = 3
MIN_VALUE_USD = 100_000.0
POSITION_FRACTION = 0.01
SPLIT_FRACTIONS = (0.50, 0.60, 0.70, 0.80)


class EventReplaySource:
    topics = ("features.snapshots",)

    def __init__(self, config: dict):
        self.positions = {
            str(symbol): [float(value) for value in values]
            for symbol, values in config["event_positions"].items()
        }
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
            instrument_id=symbol,
            side=side,
            confidence=1.0,
            mid=float(snapshot["mid_price"]),
            timestamp=snapshot["timestamp"],
            signal_meta={"source": "insider_kernel_replay", "target": target},
        )]


class ReplayClock:
    def __init__(self, value: datetime):
        self.current = value

    def __call__(self) -> datetime:
        return self.current


def build_event_positions(frames: dict, events: list[tuple[str, str]],
                          hold_sessions: int) -> dict[str, list[float]]:
    """Build causal next-bar entry/5-session exit targets per symbol."""
    by_symbol: dict[str, list[str]] = {}
    positions: dict[str, list[float]] = {}
    for symbol, series in frames.items():
        dates = list(series.index)
        by_symbol[symbol] = dates
        positions[symbol] = [0.0] * len(dates)
    for symbol, filing_date in events:
        dates = by_symbol.get(symbol)
        if not dates:
            continue
        entry = bisect.bisect_right(dates, filing_date)
        exit_index = entry + hold_sessions
        if entry >= len(dates):
            continue
        positions[symbol][entry:min(exit_index, len(dates))] = [
            1.0
        ] * (min(exit_index, len(dates)) - entry)
    return positions


def build_risk_fractions(frames: dict, events: list[tuple[str, str]],
                         base_fraction: float) -> dict[str, float]:
    """Scale notional inversely to pre-first-event daily volatility, causally."""
    first_event: dict[str, str] = {}
    for symbol, filing_date in events:
        first_event.setdefault(symbol, filing_date)
    volatilities: dict[str, float] = {}
    for symbol, filing_date in first_event.items():
        series = frames.get(symbol)
        if series is None:
            continue
        entry = bisect.bisect_right(list(series.index), filing_date)
        prices = series.to_numpy(dtype=float)[:entry]
        returns = np.diff(prices[-61:]) / prices[-61:-1] if len(prices) >= 21 else np.asarray([])
        if len(returns) >= 20 and np.all(np.isfinite(returns)):
            volatilities[symbol] = float(np.std(returns, ddof=1) * np.sqrt(252.0))
    positive = [value for value in volatilities.values() if value > 0]
    reference = float(np.median(positive)) if positive else 0.0
    fractions = {}
    for symbol in frames:
        vol = volatilities.get(symbol, reference)
        scale = np.clip(reference / vol, 0.25, 2.0) if reference > 0 and vol > 0 else 1.0
        fractions[symbol] = float(base_fraction * scale)
    return fractions


def pre_event_volatility(frames: dict, symbol: str, filing_date: str,
                         window: int = 60) -> float | None:
    """Return causal annualized volatility immediately before a filing."""
    series = frames.get(symbol)
    if series is None:
        return None
    dates = list(series.index)
    entry = bisect.bisect_right(dates, filing_date)
    prices = series.to_numpy(dtype=float)[:entry]
    if len(prices) < window + 1 or np.any(~np.isfinite(prices[-(window + 1):])):
        return None
    returns = np.diff(prices[-(window + 1):]) / prices[-(window + 1):-1]
    if len(returns) < window or np.any(~np.isfinite(returns)):
        return None
    return float(np.std(returns, ddof=1) * np.sqrt(252.0))


def filter_events_by_pre_event_vol(frames: dict, events: list[tuple[str, str]],
                                   max_volatility: float,
                                   window: int = 60) -> list[tuple[str, str]]:
    """Keep only events whose pre-filing volatility is known and bounded."""
    selected = []
    for event in events:
        volatility = pre_event_volatility(frames, event[0], event[1], window)
        if volatility is not None and volatility <= max_volatility:
            selected.append(event)
    return selected


def filter_events_by_market_return(market_frame: pd.Series,
                                   events: list[tuple[str, str]],
                                   lookback: int,
                                   min_return: float) -> list[tuple[str, str]]:
    """Keep events only when a causal market lookback return clears a floor."""
    dates = list(market_frame.index)
    prices = market_frame.to_numpy(dtype=float)
    selected = []
    for event in events:
        entry = bisect.bisect_right(dates, event[1])
        if entry < lookback or not np.all(np.isfinite(prices[entry-lookback:entry+1])):
            continue
        market_return = prices[entry] / prices[entry - lookback] - 1.0
        if market_return >= min_return:
            selected.append(event)
    return selected


def split_dates(index: list[str]) -> list[str]:
    if len(index) < 300:
        raise ValueError("insider replay requires at least 300 market dates")
    return [index[int(len(index) * fraction)] for fraction in SPLIT_FRACTIONS]


def oos_return(points, split_date: str) -> float | None:
    oos = [point for point in points if point.ts >= split_date]
    prior = [point for point in points if point.ts < split_date]
    start = prior[-1] if prior else (oos[0] if oos else None)
    end = oos[-1] if oos else None
    if start is None or end is None or start.equity <= 0:
        return None
    return float(end.equity / start.equity - 1.0)


def concentration(metrics: dict) -> dict:
    values = [float(item["realized_pnl"]) for item in metrics.get("per_instrument", {}).values()
              if item.get("realized_pnl") is not None]
    positive = sorted((value for value in values if value > 0), reverse=True)
    total = sum(values)
    return {
        "instruments": len(values),
        "positive_instrument_fraction": (sum(value > 0 for value in values) / len(values)
                                          if values else None),
        "top1_positive_pnl_share": positive[0] / total if positive and total > 0 else None,
        "top5_positive_pnl_share": sum(positive[:5]) / total if positive and total > 0 else None,
        "top10_positive_pnl_share": sum(positive[:10]) / total if positive and total > 0 else None,
        "median_instrument_realized_pnl": float(np.median(values)) if values else None,
    }


def filter_by_filing_delay(trades: list, max_days: int | None) -> list:
    """Keep trades whose transaction date was disclosed within ``max_days``.

    Both dates are known in the public filing, so this filter is causal at the
    filing timestamp. Missing transaction dates remain UNKNOWN and are removed
    when the filter is enabled rather than treated as zero delay.
    """
    if max_days is None:
        return trades
    kept = []
    for trade in trades:
        if not trade.trans_date:
            continue
        try:
            filing = datetime.fromisoformat(trade.filing_date)
            transaction = datetime.fromisoformat(trade.trans_date)
        except ValueError:
            continue
        delay = (filing - transaction).days
        if 0 <= delay <= max_days:
            kept.append(trade)
    return kept


async def main_async(args: argparse.Namespace) -> int:
    as_of = datetime.now(UTC)
    trades = [trade for year, quarter in QUARTERS
              for trade in fetch_insider_trades(year, quarter)]
    trades_before_delay_filter = len(trades)
    trades = filter_by_filing_delay(trades, args.max_filing_delay_days)
    clusters = cluster_buys(trades, min_insiders=args.min_insiders,
                            min_value_usd=args.min_value_usd)
    events = sorted(clusters)
    symbols = sorted({symbol for symbol, _ in events})
    raw = store.read(store.DAILY_BARS, symbols, as_of=as_of)
    frames = {}
    for symbol, group in raw.groupby("symbol", sort=False):
        dates = [str(value) for value in group[store.EVENT_DATE].tolist()]
        closes = group["close"].astype(float).to_numpy()
        if len(dates) >= 300 and np.all(np.isfinite(closes)) and np.all(closes > 0):
            frames[str(symbol)] = pd.Series(closes, index=dates, dtype=float)
    if len(frames) < 4:
        raise RuntimeError("insufficient insider event price coverage")

    original_event_count = len(events)
    if args.max_pre_event_volatility is not None:
        events = filter_events_by_pre_event_vol(
            frames, events, args.max_pre_event_volatility, args.volatility_window
        )
    if args.market_symbol is not None:
        market_raw = store.read(store.DAILY_BARS, args.market_symbol, as_of=as_of)
        market_group = market_raw.sort_values(store.EVENT_DATE)
        market_frame = pd.Series(
            market_group["close"].astype(float).to_numpy(),
            index=[str(value) for value in market_group[store.EVENT_DATE].tolist()],
            dtype=float,
        )
        events = filter_events_by_market_return(
            market_frame, events, args.market_lookback, args.min_market_return
        )

    positions = build_event_positions(frames, events, args.hold_sessions)
    fraction_by_instrument = (
        build_risk_fractions(frames, events, args.position_fraction)
        if args.risk_weighted else None
    )
    all_dates = sorted({date for series in frames.values() for date in series.index})
    splits = split_dates(all_dates)
    clock = ReplayClock(datetime.fromisoformat(all_dates[0]).replace(tzinfo=UTC))
    out_dir = Path("data/.kernel_replay_insider")
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / f"insider-{uuid.uuid4().hex[:10]}.sqlite3"
    service = SimulationService(
        db_path, clock=clock, equity_poll_seconds=10**9,
        source_factories={"event_replay": lambda config, _db: EventReplaySource(config)},
    )
    await service.start()
    run = await service.create_run(
        name="insider-kernel-replay", strategy_id="event_replay", universe=list(frames),
        initial_capital=100_000.0,
        config={
            "event_positions": positions,
            "position_fraction": args.position_fraction,
            "position_fraction_by_instrument": fraction_by_instrument,
            "fee_bps": args.fee_bps,
            "mid_penalty_bps": args.mid_penalty_bps,
            "allow_short": False,
            "cooldown_seconds": 0.0,
            "max_staleness_seconds": 172800.0,
            "equity_interval_minutes": 1440.0,
        },
    )
    run_id = str(run["run_id"])
    await service.start_run(run_id)
    for date in all_dates:
        timestamp = datetime.fromisoformat(date).replace(tzinfo=UTC)
        clock.current = timestamp
        for symbol, series in frames.items():
            if date not in series.index:
                continue
            index = series.index.get_loc(date)
            await service._dispatch("features.snapshots", {
                "market_id": symbol, "timestamp": timestamp,
                "mid_price": float(series.to_numpy()[index]),
                "source": "local_daily_bars", "price_basis": "unadjusted",
            })
        await service._record_equity(service._active[run_id])
    active_before_stop = service._active.get(run_id)
    risk_rejections = int(active_before_stop.risk_rejections) if active_before_stop is not None else None
    await service.stop_run(run_id)
    metrics = sim_metrics.compute_run_metrics(service.store, run_id)
    points = service.store.list_equity_points(run_id)
    trades_out = service.store.list_trades(run_id)
    max_gross = max((float(point.gross_exposure) for point in points), default=0.0)
    max_leverage = max((float(point.gross_exposure) / point.equity
                        for point in points if point.equity > 0), default=0.0)
    folds = [{
        "split_date": split,
        "oos_return": oos_return(points, split),
        "oos_closed_trades": sum(1 for trade in trades_out
                                  if trade.executed_at >= split and trade.realized_pnl is not None),
    } for split in splits]
    period_pnl: dict[str, float] = defaultdict(float)
    period_closed: dict[str, int] = defaultdict(int)
    for trade in trades_out:
        if trade.realized_pnl is None:
            continue
        executed = trade.executed_at
        if isinstance(executed, str):
            executed = datetime.fromisoformat(executed.replace("Z", "+00:00"))
        quarter = (executed.month - 1) // 3 + 1
        period = f"{executed.year}-Q{quarter}"
        period_pnl[period] += float(trade.realized_pnl)
        period_closed[period] += 1
    equity_curve = [{
        "timestamp": point.ts.isoformat() if hasattr(point.ts, "isoformat") else str(point.ts),
        "equity": float(point.equity),
        "gross_exposure": float(point.gross_exposure),
        "degraded": bool(point.degraded),
    } for point in points]
    report = {
        "generated_at": datetime.now(UTC).isoformat(), "real_data_only": True,
        "execution_kernel": "modules.simulation.SimulationService",
        "sec_quarters": QUARTERS,
        "strategy": {"family": "sec_insider_cluster_buy", "hold_sessions": args.hold_sessions,
                      "min_insiders": args.min_insiders, "min_value_usd": args.min_value_usd,
                      "max_filing_delay_days": args.max_filing_delay_days,
                      "max_pre_event_volatility": args.max_pre_event_volatility,
                      "volatility_window": args.volatility_window,
                      "market_symbol": args.market_symbol,
                      "market_lookback": args.market_lookback,
                      "min_market_return": args.min_market_return},
        "execution_config": {"fee_bps": args.fee_bps, "mid_penalty_bps": args.mid_penalty_bps,
                              "allow_short": False, "position_fraction": args.position_fraction,
                              "risk_weighted": args.risk_weighted},
        "events": len(events), "events_before_filter": original_event_count,
        "trade_quality": {"trades_before_delay_filter": trades_before_delay_filter,
                           "trades_after_delay_filter": len(trades)},
        "symbols_requested": len(symbols),
        "symbols_replayed": len(frames), "coverage": len(frames) / len(symbols),
        "candidate_family_size": (108 if args.market_symbol is not None
                                   else (54 if args.max_pre_event_volatility is not None
                                         else (36 if args.risk_weighted else 18))),
        "selection_note": "candidate was observed in the existing train/OOS optimizer; kernel replay remains independent evidence",
        "full_metrics": metrics, "folds": folds,
        "concentration": concentration(metrics),
        "calendar_period_pnl": dict(sorted(period_pnl.items())),
        "calendar_period_closed_trades": dict(sorted(period_closed.items())),
        "equity_curve": equity_curve,
        "risk_rejections": risk_rejections,
        "max_gross_exposure": max_gross,
        "max_gross_leverage": max_leverage,
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
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fee-bps", type=float, default=20.0)
    parser.add_argument("--mid-penalty-bps", type=float, default=10.0)
    parser.add_argument("--position-fraction", type=float, default=POSITION_FRACTION)
    parser.add_argument("--risk-weighted", action="store_true")
    parser.add_argument("--max-pre-event-volatility", type=float, default=None,
                        help="causal annualized volatility ceiling for event entry")
    parser.add_argument("--volatility-window", type=int, default=60)
    parser.add_argument("--market-symbol", default=None,
                        help="causal market regime symbol used to filter events")
    parser.add_argument("--market-lookback", type=int, default=20)
    parser.add_argument("--min-market-return", type=float, default=0.0)
    parser.add_argument("--hold-sessions", type=int, default=HOLD_SESSIONS)
    parser.add_argument("--min-insiders", type=int, default=MIN_INSIDERS)
    parser.add_argument("--min-value-usd", type=float, default=MIN_VALUE_USD)
    parser.add_argument("--max-filing-delay-days", type=int, default=None,
                        help="causal filing_date - transaction_date ceiling")
    parser.add_argument("--output", default="data/insider_kernel_replay.json")
    raise SystemExit(asyncio.run(main_async(parser.parse_args())))
