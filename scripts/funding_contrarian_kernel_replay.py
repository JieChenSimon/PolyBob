"""Replay funding contrarian candidates through the real SimulationService."""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

from libs.data import store
from libs.quant.edges import funding_contrarian
from libs.quant.promotion import PromotionGate
from modules.simulation import SimulationService
from modules.simulation import metrics as sim_metrics
from modules.simulation.sources import SimSignal


PRICE_TO_FUNDING = {"BTC-USDT": "BTC-PERPETUAL", "ETH-USDT": "ETH-PERPETUAL"}
THRESHOLDS = (60.0, 75.0, 90.0)
COST_MULTIPLES = (1.0, 2.0, 3.0)


class ReplayPositionSource:
    topics = ("features.snapshots",)

    def __init__(self, config: dict):
        self.positions = [float(value) for value in config["replay_positions"]]
        self.index = 0
        self.previous = 0.0

    async def on_snapshot(self, topic: str, snapshot: dict) -> list[SimSignal]:
        if self.index >= len(self.positions):
            return []
        target = self.positions[self.index]
        self.index += 1
        if target == self.previous:
            return []
        previous = self.previous
        self.previous = target
        side = "buy" if target > 0 or (target == 0 and previous < 0) else "sell"
        return [SimSignal(
            instrument_id=str(snapshot["market_id"]), side=side, confidence=1.0,
            mid=float(snapshot["mid_price"]), timestamp=snapshot["timestamp"],
            signal_meta={"source": "funding_contrarian_kernel_replay", "target": target},
        )]


class ReplayClock:
    def __init__(self, value: datetime):
        self.current = value

    def __call__(self) -> datetime:
        return self.current


def _read_series(price_symbol: str):
    funding_symbol = PRICE_TO_FUNDING[price_symbol]
    prices = store.read(store.DAILY_BARS, price_symbol)
    funding = store.read(store.FUNDING_RATES, funding_symbol)
    price_map = dict(zip(prices["event_date"].astype(str), prices["close"].astype(float)))
    funding_map = dict(zip(funding["event_date"].astype(str), funding["rate"].astype(float)))
    dates = sorted(set(price_map) & set(funding_map))
    if len(dates) < 300:
        raise RuntimeError(f"insufficient aligned history for {price_symbol}: {len(dates)}")
    return dates, np.asarray([price_map[d] for d in dates]), np.asarray([funding_map[d] for d in dates])


async def replay_symbol(
    symbol: str, dates: list[str], prices: np.ndarray, funding: np.ndarray,
    positions: np.ndarray, split_date: str, out_dir: Path, cost_multiple: float,
) -> dict:
    timestamps = [datetime.fromisoformat(day).replace(tzinfo=UTC) for day in dates]
    clock = ReplayClock(timestamps[0])
    db_path = out_dir / f"{symbol}-{uuid.uuid4().hex[:8]}.sqlite3"
    service = SimulationService(
        db_path, clock=clock, equity_poll_seconds=10**9,
        source_factories={"replay_positions": lambda config, _db: ReplayPositionSource(config)},
    )
    await service.start()
    run = await service.create_run(
        name=f"funding:{symbol}", strategy_id="replay_positions", universe=[symbol],
        initial_capital=10_000.0,
        config={
            "replay_positions": positions.tolist(),
            "position_fraction": 0.10,
            "fee_bps": 20.0 * cost_multiple,
            "mid_penalty_bps": 10.0 * cost_multiple,
            "allow_short": True,
            "funding_enabled": True,
            "cooldown_seconds": 0.0,
            "max_staleness_seconds": 172800.0,
            "equity_interval_minutes": 1440.0,
        },
    )
    run_id = str(run["run_id"])
    await service.start_run(run_id)
    for day, price, rate, timestamp in zip(dates, prices, funding, timestamps):
        clock.current = timestamp
        await service._dispatch("features.snapshots", {
            "market_id": symbol, "timestamp": timestamp, "mid_price": float(price),
            "funding_rate": float(rate), "source": "local_daily_bars_deribit_funding",
        })
        await service._record_equity(service._active[run_id])
    await service.stop_run(run_id)
    metrics = sim_metrics.compute_run_metrics(service.store, run_id)
    points = service.store.list_equity_points(run_id)
    oos_points = [point for point in points if point.ts >= split_date]
    prior = [point for point in points if point.ts < split_date]
    start = prior[-1] if prior else (oos_points[0] if oos_points else None)
    end = oos_points[-1] if oos_points else None
    oos_return = end.equity / start.equity - 1.0 if start and end and start.equity > 0 else None
    oos_returns = [
        current.equity / previous.equity - 1.0
        for previous, current in zip(points, points[1:])
        if current.ts >= split_date and previous.equity > 0
    ]
    funding_pnl = metrics.get("funding_pnl", 0.0)
    await service.stop()
    for suffix in ("", "-wal", "-shm"):
        db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)
    return {
        "symbol": symbol, "split_date": split_date, "oos_return": oos_return,
        "oos_returns": oos_returns, "funding_pnl": funding_pnl,
        "metrics": metrics,
    }


async def main_async(output: Path) -> None:
    series = {symbol: _read_series(symbol) for symbol in PRICE_TO_FUNDING}
    split_indices = [int(len(next(iter(series.values()))[0]) * fraction) for fraction in (0.40, 0.55, 0.70, 0.85)]
    report_candidates = []
    out_dir = Path("data/.kernel_replay_funding")
    out_dir.mkdir(parents=True, exist_ok=True)
    for threshold in THRESHOLDS:
        by_cost = {}
        for multiple in COST_MULTIPLES:
            fold_rows = []
            all_returns = []
            for split_index in split_indices:
                results = []
                for symbol, (dates, prices, funding) in series.items():
                    positions = funding_contrarian(prices, funding, threshold_pct=threshold)
                    results.append(await replay_symbol(
                        symbol, dates, prices, funding, positions, dates[split_index],
                        out_dir, multiple,
                    ))
                oos = [r["oos_return"] for r in results if r["oos_return"] is not None]
                all_returns.extend(value for r in results for value in r["oos_returns"])
                fold_rows.append({
                    "split_date": results[0]["split_date"],
                    "median_oos_return": float(np.median(oos)) if oos else None,
                    "positive_oos_fraction": float(np.mean(np.asarray(oos) > 0)) if oos else None,
                    "median_funding_pnl": float(np.median([r["funding_pnl"] for r in results])),
                    "median_max_drawdown": float(np.median([r["metrics"]["max_drawdown"] for r in results])),
                    "median_closed_trades": float(np.median([r["metrics"]["closed_trade_count"] for r in results])),
                })
            by_cost[str(multiple)] = {"folds": fold_rows, "returns": all_returns}
        base = by_cost["1.0"]
        stability = float(np.mean([
            (row["median_oos_return"] or 0.0) > 0 for row in base["folds"]
        ]))
        returns_by_cost = {float(k): np.asarray(v["returns"], dtype=float) for k, v in by_cost.items()}
        gate = PromotionGate(n_trials=len(THRESHOLDS) * len(COST_MULTIPLES), min_dsr=0.90,
                             min_observations=200, min_oos_stability_rate=0.5, cost_min_sharpe=0.3)
        decision = gate.evaluate(
            returns_by_cost[1.0],
            cost_returns_fn=lambda multiple: returns_by_cost[float(multiple)],
            oos_stability_rate=stability,
        )
        report_candidates.append({
            "threshold_pct": threshold,
            "costs": {key: {k: v for k, v in value.items() if k != "returns"} for key, value in by_cost.items()},
            "promotion": decision.to_dict(),
        })
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "real_data_only": True,
        "execution_kernel": "modules.simulation.SimulationService",
        "strategy": "funding_contrarian",
        "symbols": list(PRICE_TO_FUNDING),
        "funding_sources": list(PRICE_TO_FUNDING.values()),
        "candidates": report_candidates,
        "status": "replay_only_not_promoted",
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/funding_contrarian_kernel_replay.json"))
    args = parser.parse_args()
    asyncio.run(main_async(args.output))
