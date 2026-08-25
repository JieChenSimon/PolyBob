"""Replay the deep-drawdown candidate through the real Paper Lab kernel.

This is an evidence runner, not a promotion command.  It uses real local daily
bars and the same ``SimulationService`` fill/accounting/ledger path as Paper
Trading.  Historical PIT fundamentals and historical executable BBO/depth are
not fabricated: the report keeps their gates UNKNOWN_NO_TRADE.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import logging
import math
import sys
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from libs.data import store
from libs.db import fact_store
from modules.simulation import metrics as sim_metrics
from modules.simulation.service import SimulationService
from scripts.simulation_research_pipeline import ProgressReporter, ReplayClock, _bars, _date
from scripts.deep_drawdown_research import _first_drawdown_events, _fundamental_quality


HORIZONS = (21, 63, 126, 252)
COST_MULTIPLES = (1.0, 2.0, 3.0)
MIN_ROWS = 120
INITIAL_CAPITAL = 10_000.0
DOMAIN_COST_BPS = {"a_share": 40.0, "us_equity": 20.0, "crypto": 35.0}


def _domain(symbol: str) -> str:
    if symbol.isdigit():
        return "a_share"
    if symbol.endswith("-USDT"):
        return "crypto"
    return "us_equity"


def _symbols_from_file(path: str) -> list[str]:
    """Read a plain symbol list or only READY symbols from a discovery manifest."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        if "candidates" in payload:
            payload = [
                row.get("symbol") for row in payload.get("candidates", [])
                if row.get("status") == "READY_FOR_RESEARCH"
            ]
        else:
            payload = payload.get("candidate_symbols", [])
    return [str(item).strip() for item in payload if str(item).strip()]


def _csv_ints(value: str) -> tuple[int, ...]:
    values = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    if not values or any(item <= 0 for item in values):
        raise argparse.ArgumentTypeError("expected comma-separated positive integers")
    return values


def _csv_floats(value: str) -> tuple[float, ...]:
    values = tuple(float(item.strip()) for item in value.split(",") if item.strip())
    if not values or any(item <= 0 for item in values):
        raise argparse.ArgumentTypeError("expected comma-separated positive numbers")
    return values


def _event_summaries(trades: list[Any], *, split: datetime) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for trade in trades:
        try:
            meta = json.loads(trade.signal_meta) if isinstance(trade.signal_meta, str) else trade.signal_meta
        except (TypeError, ValueError):
            meta = {}
        if not isinstance(meta, dict) or meta.get("source") != "deep_drawdown_rebound_v1":
            continue
        event_id = str(meta.get("event_id", "unknown"))
        event = grouped.setdefault(event_id, {
            "event_id": event_id,
            "event_date": meta.get("event_date"),
            "event_index": meta.get("event_index"),
            "realized_pnl": 0.0,
            "fees": 0.0,
            "trade_count": 0,
            "closed_trade_count": 0,
        })
        event["realized_pnl"] += float(trade.realized_pnl or 0.0)
        event["fees"] += float(trade.fee or 0.0)
        event["trade_count"] += 1
        if trade.realized_pnl is not None:
            event["closed_trade_count"] += 1
    summaries = []
    for event in grouped.values():
        event_date = event.get("event_date")
        if not event_date:
            event["status"] = "UNKNOWN"
            event["reason"] = "missing_event_date"
            summaries.append(event)
            continue
        event_ts = datetime.fromisoformat(str(event_date).replace("Z", "+00:00"))
        event_ts = event_ts if event_ts.tzinfo else event_ts.replace(tzinfo=UTC)
        event["oos"] = event_ts >= split
        event["return_on_nav"] = event["realized_pnl"] / INITIAL_CAPITAL
        event["status"] = "ANALYZED" if event["closed_trade_count"] > 0 else "UNKNOWN"
        event["reason"] = None if event["status"] == "ANALYZED" else "position_not_closed_in_window"
        summaries.append(event)
    return sorted(summaries, key=lambda item: (str(item.get("event_date")), item["event_id"]))


def _event_stats(events: list[dict[str, Any]], *, oos: bool | None = None,
                 cost_multiple: float = 1.0) -> dict[str, Any]:
    selected = [event for event in events if oos is None or event.get("oos") is oos]
    complete = [event for event in selected if event.get("status") == "ANALYZED"]
    values = [float(event["return_on_nav"]) - float(event["fees"]) / INITIAL_CAPITAL * (cost_multiple - 1.0)
              for event in complete]
    if not values:
        return {"status": "UNKNOWN", "n_events": len(selected), "n_complete": 0,
                "mean_net_return": None, "win_rate": None, "max_drawdown": None}
    wealth = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for value in values:
        wealth *= 1.0 + value
        peak = max(peak, wealth)
        max_drawdown = max(max_drawdown, (peak - wealth) / peak)
    return {
        "status": "ANALYZED",
        "n_events": len(selected),
        "n_complete": len(complete),
        "mean_net_return": sum(values) / len(values),
        "median_net_return": sorted(values)[len(values) // 2],
        "win_rate": sum(value > 0 for value in values) / len(values),
        "max_drawdown": max_drawdown,
        "cost_multiple": cost_multiple,
    }


def _fundamental_gate_status(
    events: list[dict[str, Any]], allowed_event_dates: set[str] | None,
) -> str:
    """Separate row-level event-date approval from global trade approval."""
    if allowed_event_dates is None:
        return "UNKNOWN_NO_TRADE"
    event_dates = {
        str(event.get("event_date", ""))[:10]
        for event in events
        if event.get("event_date")
    }
    return "PASS_EVENT_DATE_GATE" if event_dates & allowed_event_dates else "UNKNOWN_NO_TRADE"


def _candidate_symbols(
    symbols: list[str], rows_by_symbol: dict[str, list[dict[str, Any]]],
    quality_dates_by_symbol: dict[str, set[str]] | None = None,
    *, drawdown_fraction: float = 0.50,
) -> list[str]:
    """Keep the replay matrix bounded to symbols with an eligible event.

    The daily-bar store contains a much larger discovery universe than the
    deep-drawdown strategy's event universe. Replaying every stored symbol
    creates thousands of empty SimulationService cases and can saturate a CPU
    for hours. Quality-only runs additionally require at least one row-level
    quality-approved event; symbols with only UNKNOWN/FAIL dates are correctly
    excluded from trading and remain represented by the quality summary.
    """
    if quality_dates_by_symbol is not None:
        return [symbol for symbol in symbols if quality_dates_by_symbol.get(symbol)]
    candidates: list[str] = []
    for symbol in symbols:
        rows = rows_by_symbol[symbol]
        peak = None
        triggered = False
        for row in rows:
            close = row.get("close")
            if close is None:
                continue
            drawdown = None if peak is None else 1.0 - float(close) / peak
            current = drawdown is not None and drawdown >= drawdown_fraction
            if current and not triggered:
                candidates.append(symbol)
                break
            triggered = current
            peak = max(peak or float(close), float(close))
    return candidates


async def _run_case(symbol: str, rows: list[dict[str, Any]], *, hold_days: int,
                    cost_multiple: float, db_path: Path, name: str,
                    confirmation_bars: int = 0, probe_fraction: float = 0.0,
                    allowed_event_dates: set[str] | None = None,
                    max_nav_fraction: float = 0.05,
                    drawdown_fraction: float = 0.50) -> dict[str, Any]:
    if len(rows) < MIN_ROWS:
        return {"symbol": symbol, "domain": _domain(symbol), "status": "BLOCKED",
                "reason": f"rows<{MIN_ROWS}", "rows": len(rows)}
    clock = ReplayClock(rows[0]["event_at"])
    domain = _domain(symbol)
    round_trip_bps = DOMAIN_COST_BPS[domain] * cost_multiple
    service = SimulationService(db_path, clock=clock, equity_poll_seconds=10**9)
    try:
        await service.start()
        run = await service.create_run(
            name=name,
            strategy_id="deep_drawdown_rebound_v1",
            universe=[symbol],
            initial_capital=INITIAL_CAPITAL,
            config={
                "drawdown_fraction": drawdown_fraction,
                "tranche_delays_days": [0, 5, 20],
                "hold_days": hold_days,
                "max_nav_fraction": max_nav_fraction,
                "position_fraction": max_nav_fraction,
                "confirmation_bars": confirmation_bars,
                "probe_fraction": probe_fraction,
                "allow_short": False,
                # With daily bars there is no historical BBO.  Represent the
                # declared round-trip cost as two fee legs and do not invent a
                # spread/depth observation.
                "fee_bps": round_trip_bps / 2.0,
                "mid_penalty_bps": 0.0,
                "max_staleness_seconds": 172800.0,
                "equity_interval_minutes": 1440.0,
                "record_equity_on_fill": False,
                "cooldown_seconds": 0.0,
                "allowed_event_dates": sorted(allowed_event_dates) if allowed_event_dates is not None else None,
            },
        )
        run_id = str(run["run_id"])
        await service.start_run(run_id)
        split = rows[0]["event_at"] + (rows[-1]["event_at"] - rows[0]["event_at"]) * 0.70
        for index, row in enumerate(rows):
            clock.current = row["event_at"]
            await service._dispatch("features.snapshots", {
                "market_id": symbol,
                "timestamp": row["event_at"],
                "mid_price": row["close"],
                "source": row.get("source"),
                "price_basis": row.get("price_basis"),
            })
            active = service._active.get(run_id)
            if active is not None:
                await service._record_equity(active)
        clock.current = rows[-1]["event_at"]
        active = service._active.get(run_id)
        execution_diagnostics = {
            "signal_count": int(active.signal_count) if active is not None else None,
            "stale_signal_count": int(active.stale_signal_count) if active is not None else None,
            "unfillable_signal_count": int(active.unfillable_signal_count) if active is not None else None,
            "risk_rejection_count": int(active.risk_rejections) if active is not None else None,
            "risk_rejection_reasons": (
                sorted({reason for event in active.risk_rejection_events
                        for reason in event.get("reasons", [])})
                if active is not None else []
            ),
            "bankruptcy_block_count": int(active.bankruptcy_block_count) if active is not None else None,
            "bankrupt": bool(active is not None and active.bankruptcy_block_count > 0),
        }
        await service.stop_run(run_id)
        trades = service.store.list_trades(run_id)
        events = _event_summaries(trades, split=split)
        metrics = sim_metrics.compute_run_metrics(service.store, run_id)
        fundamental_status = _fundamental_gate_status(events, allowed_event_dates)
        return {
            "symbol": symbol,
            "domain": domain,
            "status": "ANALYZED",
            "rows": len(rows),
            "start": rows[0]["event_at"].date().isoformat(),
            "end": rows[-1]["event_at"].date().isoformat(),
            "hold_days": hold_days,
            "drawdown_fraction": drawdown_fraction,
            "cost_multiple": cost_multiple,
            "confirmation_bars": confirmation_bars,
            "probe_fraction": probe_fraction,
            "max_nav_fraction": max_nav_fraction,
            "fundamental_quality_gate": allowed_event_dates is not None,
            "round_trip_cost_bps": round_trip_bps,
            "metrics": metrics,
            "execution_diagnostics": execution_diagnostics,
            "events": events,
            "event_stats": {
                "all": _event_stats(events, cost_multiple=cost_multiple),
                "oos": _event_stats(events, oos=True, cost_multiple=cost_multiple),
                "cost_stress": [_event_stats(events, cost_multiple=multiple)
                                 for multiple in COST_MULTIPLES],
            },
            "pit_status": "UNKNOWN",
            "fundamental_status": fundamental_status,
            "executable_quote_status": "UNKNOWN_NO_TRADE",
            "promotion": "BLOCKED",
            "promotion_reason": (
                "global_historical_pit_or_executable_quote_unknown"
                if fundamental_status == "PASS_EVENT_DATE_GATE"
                else "fundamental_or_global_historical_pit_or_executable_quote_unknown"
            ),
        }
    finally:
        await service.stop()
        fact_store.close_writer_connections(db_path)
        for suffix in ("", "-wal", "-shm"):
            db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)
        gc.collect()


async def run(args: argparse.Namespace) -> dict[str, Any]:
    available = set(store.symbols(store.DAILY_BARS))
    if args.symbols:
        requested = [item.strip() for item in args.symbols.split(",") if item.strip()]
    elif args.symbols_file:
        requested = _symbols_from_file(args.symbols_file)
    else:
        requested = sorted(available)
    symbols = [symbol for symbol in requested if symbol in available]
    missing = [symbol for symbol in requested if symbol not in available]
    rows_by_symbol = {symbol: _bars(symbol, as_of=datetime.now(UTC), start=None, end=None)
                      for symbol in symbols}
    quality_dates_by_symbol: dict[str, set[str]] = {}
    if args.fundamental_quality_only:
        quality_as_of = datetime.now(UTC)
        for symbol in symbols:
            frame = store.read(store.DAILY_BARS, symbol, as_of=quality_as_of)
            quality_dates_by_symbol[symbol] = {
                event["event_date"]
                for event in _first_drawdown_events(frame, threshold=min(args.drawdown_fractions))
                if _fundamental_quality(symbol, event["event_date"], quality_as_of)["status"] == "PASS"
            }
    replay_symbols = _candidate_symbols(
        symbols, rows_by_symbol,
        quality_dates_by_symbol if args.fundamental_quality_only else None,
        drawdown_fraction=min(args.drawdown_fractions),
    )
    cases = [(symbol, drawdown_fraction, hold_days, multiple)
             for symbol in replay_symbols
             for drawdown_fraction in args.drawdown_fractions
             for hold_days in args.hold_days
             for multiple in args.cost_multiples]
    if len(cases) > args.max_cases:
        raise ValueError(
            f"replay case count {len(cases)} exceeds --max-cases={args.max_cases}; "
            "narrow --hold-days/--cost-multiples or raise the limit explicitly"
        )
    progress = ProgressReporter(Path(args.progress), len(cases))
    results: list[dict[str, Any]] = []
    for symbol, drawdown_fraction, hold_days, multiple in cases:
        db_path = Path(args.output_dir) / f"{symbol}-{drawdown_fraction:.2f}-{hold_days}d-{multiple:g}x-{uuid.uuid4().hex[:8]}.sqlite3"
        result = await _run_case(symbol, rows_by_symbol[symbol], hold_days=hold_days,
                                 cost_multiple=multiple, db_path=db_path,
                                 name=f"deep-drawdown:{symbol}:{drawdown_fraction:.2f}:{hold_days}d:{multiple:g}x",
                                 confirmation_bars=args.confirmation_bars,
                                 probe_fraction=args.probe_fraction,
                                 max_nav_fraction=args.max_nav_fraction,
                                 drawdown_fraction=drawdown_fraction,
                                 allowed_event_dates=(quality_dates_by_symbol[symbol]
                                                       if args.fundamental_quality_only else None))
        results.append(result)
        progress.complete_one(f"{symbol}:{hold_days}d:{multiple:g}x")
    report = {
        "schema_version": "deep-drawdown-kernel-replay-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "real_data_only": True,
        "requested_symbols": requested,
        "missing_symbols": missing,
        "universe_count": len(replay_symbols),
        "available_symbol_count": len(symbols),
        "candidate_filter": (
            "drawdown_event_and_row_level_quality_pass"
            if args.fundamental_quality_only else "drawdown_event"
        ),
        "case_count": len(cases),
        "fundamental_quality_only": bool(args.fundamental_quality_only),
        "max_nav_fraction": args.max_nav_fraction,
        "drawdown_fractions": args.drawdown_fractions,
        "results": results,
        "promotion": {"status": "BLOCKED", "reason": "PIT/fundamental/executable quote gates UNKNOWN"},
        "progress": json.loads(Path(args.progress).read_text(encoding="utf-8")),
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
                                 encoding="utf-8")
    return report


def main() -> int:
    try:
        import structlog
        structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))
    except Exception:  # pragma: no cover - logging configuration is optional
        pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--symbols-file", default=None,
                        help="JSON list or discovery manifest with candidate_symbols")
    parser.add_argument("--output", default="data/deep_drawdown_kernel_replay.json")
    parser.add_argument("--progress", default="data/deep_drawdown_kernel_progress.json")
    parser.add_argument("--output-dir", default="data/.kernel_replay_deep_drawdown")
    parser.add_argument("--confirmation-bars", type=int, default=0)
    parser.add_argument("--probe-fraction", type=float, default=0.0)
    parser.add_argument("--max-nav-fraction", type=float, default=0.05,
                        help="bounded per-instrument NAV target; default 0.05")
    parser.add_argument("--drawdown-fractions", type=_csv_floats, default=(0.30, 0.40, 0.50),
                        help="pre-registered comma-separated drawdown thresholds; default: 0.30,0.40,0.50")
    parser.add_argument("--hold-days", type=_csv_ints, default=HORIZONS,
                        help="comma-separated holding periods; default: 21,63,126,252")
    parser.add_argument("--cost-multiples", type=_csv_floats, default=COST_MULTIPLES,
                        help="comma-separated cost stress multiples; default: 1,2,3")
    parser.add_argument("--max-cases", type=int, default=120,
                        help="fail closed before an oversized SimulationService matrix")
    parser.add_argument("--fundamental-quality-only", action="store_true",
                        help="trade only drawdown dates passing the row-level SEC quality audit")
    args = parser.parse_args()
    if not 0.0 < args.max_nav_fraction <= 0.25:
        parser.error("--max-nav-fraction must be >0 and <=0.25")
    if any(not 0.0 < value < 1.0 for value in args.drawdown_fractions):
        parser.error("--drawdown-fractions values must be between 0 and 1")
    report = asyncio.run(run(args))
    print(json.dumps({"symbols": report["universe_count"], "cases": report["case_count"],
                      "promotion": report["promotion"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
