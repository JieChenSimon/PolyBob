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


async def _run_case(symbol: str, rows: list[dict[str, Any]], *, hold_days: int,
                    cost_multiple: float, db_path: Path, name: str) -> dict[str, Any]:
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
                "drawdown_fraction": 0.50,
                "tranche_delays_days": [0, 5, 20],
                "hold_days": hold_days,
                "max_nav_fraction": 0.05,
                "position_fraction": 0.05,
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
        await service.stop_run(run_id)
        trades = service.store.list_trades(run_id)
        events = _event_summaries(trades, split=split)
        metrics = sim_metrics.compute_run_metrics(service.store, run_id)
        return {
            "symbol": symbol,
            "domain": domain,
            "status": "ANALYZED",
            "rows": len(rows),
            "start": rows[0]["event_at"].date().isoformat(),
            "end": rows[-1]["event_at"].date().isoformat(),
            "hold_days": hold_days,
            "cost_multiple": cost_multiple,
            "round_trip_cost_bps": round_trip_bps,
            "metrics": metrics,
            "events": events,
            "event_stats": {
                "all": _event_stats(events, cost_multiple=cost_multiple),
                "oos": _event_stats(events, oos=True, cost_multiple=cost_multiple),
                "cost_stress": [_event_stats(events, cost_multiple=multiple)
                                 for multiple in COST_MULTIPLES],
            },
            "pit_status": "UNKNOWN",
            "fundamental_status": "UNKNOWN_NO_TRADE",
            "executable_quote_status": "UNKNOWN_NO_TRADE",
            "promotion": "BLOCKED",
        }
    finally:
        await service.stop()
        fact_store.close_writer_connections(db_path)
        for suffix in ("", "-wal", "-shm"):
            db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)
        gc.collect()


async def run(args: argparse.Namespace) -> dict[str, Any]:
    available = set(store.symbols(store.DAILY_BARS))
    requested = [item.strip() for item in args.symbols.split(",") if item.strip()] if args.symbols else sorted(available)
    symbols = [symbol for symbol in requested if symbol in available]
    missing = [symbol for symbol in requested if symbol not in available]
    rows_by_symbol = {symbol: _bars(symbol, as_of=datetime.now(UTC), start=None, end=None)
                      for symbol in symbols}
    cases = [(symbol, hold_days, multiple)
             for symbol in symbols
             for hold_days in HORIZONS
             for multiple in COST_MULTIPLES]
    progress = ProgressReporter(Path(args.progress), len(cases))
    results: list[dict[str, Any]] = []
    for symbol, hold_days, multiple in cases:
        db_path = Path(args.output_dir) / f"{symbol}-{hold_days}d-{multiple:g}x-{uuid.uuid4().hex[:8]}.sqlite3"
        result = await _run_case(symbol, rows_by_symbol[symbol], hold_days=hold_days,
                                 cost_multiple=multiple, db_path=db_path,
                                 name=f"deep-drawdown:{symbol}:{hold_days}d:{multiple:g}x")
        results.append(result)
        progress.complete_one(f"{symbol}:{hold_days}d:{multiple:g}x")
    report = {
        "schema_version": "deep-drawdown-kernel-replay-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "real_data_only": True,
        "requested_symbols": requested,
        "missing_symbols": missing,
        "universe_count": len(symbols),
        "case_count": len(cases),
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
    parser.add_argument("--output", default="data/deep_drawdown_kernel_replay.json")
    parser.add_argument("--progress", default="data/deep_drawdown_kernel_progress.json")
    parser.add_argument("--output-dir", default="data/.kernel_replay_deep_drawdown")
    args = parser.parse_args()
    report = asyncio.run(run(args))
    print(json.dumps({"symbols": report["universe_count"], "cases": report["case_count"],
                      "promotion": report["promotion"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
