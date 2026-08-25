"""Replay a real OKX historical L2 depth-imbalance candidate through Paper Lab.

This is deliberately a spot-BTC execution diagnostic.  It must not be used as
the execution source for the BTC 5-minute binary-contract strategy: that market
has a different instrument and venue.  Every quote used here comes from the
official OKX historical L2 archive and every fill is linked to the persisted
quote observation that caused the signal.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.dataset as ds
import structlog

from modules.simulation import SimulationService
from modules.simulation import metrics as sim_metrics
from modules.simulation.sources import SimSignal


DEFAULT_DATASET = Path(
    "data/datasets/parts/okx_historical_orderbook_sampled_1s/"
    "symbol=BTC-USDT/2025-08-01.parquet"
)


class CpuBudgetThrottle:
    """Bound this single SQLite-heavy replay to at most 30% CPU share."""

    def __init__(self, target: float = 0.30):
        self.target = min(0.50, max(0.05, float(target)))
        self.wall = time.monotonic()
        self.cpu = time.process_time()

    def pause(self) -> None:
        wall = time.monotonic() - self.wall
        cpu = time.process_time() - self.cpu
        if wall < 0.05 or cpu <= 0:
            return
        desired_wall = cpu / self.target
        if desired_wall > wall:
            time.sleep(min(desired_wall - wall, 1.0))
        self.wall = time.monotonic()
        self.cpu = time.process_time()


@dataclass
class Clock:
    current: datetime

    def __call__(self) -> datetime:
        return self.current


class ReplaySource:
    topics = ("features.snapshots",)

    async def on_snapshot(self, topic: str, snapshot: dict) -> list[SimSignal]:
        if snapshot.get("target") is None:
            return []
        target = float(snapshot["target"])
        previous = float(snapshot["previous_target"])
        if target == previous:
            return []
        side = "buy" if target > previous else "sell"
        return [SimSignal(
            instrument_id="BTC-USDT",
            side=side,
            confidence=1.0,
            bid=float(snapshot["bid"]),
            ask=float(snapshot["ask"]),
            bid_depth=float(snapshot["bid_depth"]),
            ask_depth=float(snapshot["ask_depth"]),
            mid=float(snapshot["mid"]),
            timestamp=snapshot["timestamp"],
            signal_meta={
                **dict(snapshot["signal_meta"]),
                "position_fraction": float(snapshot["position_fraction"]),
            },
        )]


def load_quotes(path: Path, *, sample_seconds: int = 5) -> list[dict]:
    if sample_seconds <= 0:
        raise ValueError("sample_seconds must be positive")
    if not path.exists():
        raise FileNotFoundError(path)
    table = ds.dataset(path, format="parquet").to_table(
        columns=[
            "event_at", "event_ts_ms", "best_bid", "best_ask",
            "bid_depth_top20", "ask_depth_top20", "raw_archive_sha256", "source",
        ]
    )
    rows = sorted(table.to_pylist(), key=lambda row: int(row["event_ts_ms"]))
    if not rows:
        raise ValueError(f"empty historical quote dataset: {path}")
    first_second = int(rows[0]["event_ts_ms"]) // 1000
    return [
        row for row in rows
        if (int(row["event_ts_ms"]) // 1000 - first_second) % sample_seconds == 0
    ]


def _imbalance(row: dict) -> float:
    bid = float(row["bid_depth_top20"])
    ask = float(row["ask_depth_top20"])
    total = bid + ask
    return (bid - ask) / total if total > 0 else 0.0


def next_target(previous: float, imbalance: float, *, enter: float, exit: float) -> float:
    """Stateful, causal rule; no future prices or future quotes are read."""
    if previous > 0 and imbalance <= exit:
        return 0.0
    if previous < 0 and imbalance >= -exit:
        return 0.0
    if previous == 0 and imbalance >= enter:
        return 1.0
    if previous == 0 and imbalance <= -enter:
        return -1.0
    return previous


async def replay(
    rows: list[dict], output_dir: Path, *, enter: float = 0.65, exit: float = 0.15,
    position_fraction: float = 0.10, impact_coefficient: float = 0.10,
    invert_signal: bool = False, feature_mode: str = "depth_imbalance",
    lookback_rows: int = 4, momentum_enter: float = 50.0,
    momentum_exit: float = 10.0,
) -> dict:
    if not rows:
        raise ValueError("rows must not be empty")
    if feature_mode == "depth_imbalance" and not 0 < exit < enter < 1:
        raise ValueError("depth_imbalance requires 0 < exit < enter < 1")
    if feature_mode == "momentum" and not 0 <= exit < enter:
        raise ValueError("momentum requires 0 <= exit < enter")
    if feature_mode == "combined" and not 0 < exit < enter < 1:
        raise ValueError("combined requires depth 0 < exit < enter < 1")
    if feature_mode in {"momentum", "combined"} and not 0 <= momentum_exit < momentum_enter:
        raise ValueError("momentum thresholds require 0 <= momentum_exit < momentum_enter")
    if not 0 < position_fraction <= 1 or impact_coefficient < 0:
        raise ValueError("position_fraction must be in (0, 1] and impact_coefficient non-negative")
    if feature_mode not in {"depth_imbalance", "momentum", "combined"} or lookback_rows <= 0:
        raise ValueError("feature_mode must be depth_imbalance, momentum, or combined and lookback_rows positive")
    output_dir.mkdir(parents=True, exist_ok=True)
    db_path = output_dir / f"okx-l2-imbalance-{uuid.uuid4().hex[:8]}.sqlite3"
    first = datetime.fromisoformat(rows[0]["event_at"])
    clock = Clock(first)
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))
    service = SimulationService(
        db_path,
        clock=clock,
        equity_poll_seconds=10**9,
        source_factories={"okx_l2_imbalance": lambda config, _db: ReplaySource()},
    )
    await service.start()
    run = await service.create_run(
        name="okx-l2-imbalance:2025-08-01",
        strategy_id="okx_l2_imbalance",
        universe=["BTC-USDT"],
        initial_capital=10_000.0,
        config={
            "position_fraction": position_fraction,
            "position_fraction_basis": "initial_capital",
            "fee_bps": 5.0,
            "mid_penalty_bps": 2.0,
            "allow_short": True,
            "cooldown_seconds": 30.0,
            "max_staleness_seconds": 30.0,
            "equity_interval_minutes": 1.0,
            "record_equity_on_fill": True,
            "min_cash_buffer": 0.0,
            "impact_coefficient": impact_coefficient,
        },
    )
    run_id = str(run["run_id"])
    await service.start_run(run_id)
    active = service._active[run_id]
    target = 0.0
    signals = 0
    linked_observations = 0
    throttle = CpuBudgetThrottle()
    mid_history: list[float] = []
    depth_target = 0.0
    momentum_target = 0.0
    for row in rows:
        observed_at = datetime.fromisoformat(row["event_at"])
        clock.current = observed_at
        mid = (float(row["best_bid"]) + float(row["best_ask"])) / 2.0
        depth_value = _imbalance(row)
        momentum_value = (
            (mid / mid_history[-lookback_rows] - 1.0) * 10_000.0
            if len(mid_history) >= lookback_rows else None
        )
        feature_value = (
            momentum_value if feature_mode == "momentum" else
            depth_value if feature_mode == "depth_imbalance" else
            {"depth_imbalance": depth_value, "momentum_bps": momentum_value}
            if feature_mode == "combined" else None
        )
        mid_history.append(mid)
        if feature_value is None or (feature_mode == "combined" and momentum_value is None):
            active.marks["BTC-USDT"] = mid
            await service._record_equity(active)
            throttle.pause()
            continue
        if feature_mode == "combined":
            base_depth_target = -depth_target if invert_signal else depth_target
            base_depth_state = next_target(base_depth_target, depth_value, enter=enter, exit=exit)
            next_depth_target = -base_depth_state if invert_signal else base_depth_state
            next_momentum_target = next_target(
                momentum_target, momentum_value, enter=momentum_enter, exit=momentum_exit,
            )
            next_state = next_momentum_target if next_depth_target == next_momentum_target else 0.0
            depth_target = next_depth_target
            momentum_target = next_momentum_target
        else:
            base_target = -target if invert_signal else target
            base_state = next_target(base_target, feature_value, enter=enter, exit=exit)
            next_state = -base_state if invert_signal else base_state
        if next_state != target:
            observation_id = f"okx-l2:{row['event_ts_ms']}"
            observation = await service.record_quote_observation(
                run_id,
                observation_id=observation_id,
                instrument_id="BTC-USDT",
                observed_at=row["event_at"],
                bid=float(row["best_bid"]),
                ask=float(row["best_ask"]),
                bid_depth=float(row["bid_depth_top20"]),
                ask_depth=float(row["ask_depth_top20"]),
                source=str(row["source"]),
                raw_payload_sha256=str(row["raw_archive_sha256"]),
                sequence_id=str(row["event_ts_ms"]),
                metadata={
                    "history_scope": "historical_orderbook_sampled",
                    "sampling_interval_ms": 1000,
                    "decision_rule": f"{feature_mode}_stateful",
                    "depth_levels": 20,
                },
            )
            await service._dispatch("features.snapshots", {
                "market_id": "BTC-USDT",
                "timestamp": observed_at,
                "mid": (float(row["best_bid"]) + float(row["best_ask"])) / 2.0,
                "bid": float(row["best_bid"]), "ask": float(row["best_ask"]),
                "bid_depth": float(row["bid_depth_top20"]),
                "ask_depth": float(row["ask_depth_top20"]),
                "target": next_state, "previous_target": target,
                "position_fraction": position_fraction * abs(next_state),
                "signal_meta": {
                    "source": "okx_l2_imbalance_replay",
                    "quote_source": str(row["source"]),
                    "quote_observation_id": observation["observation_id"],
                    "raw_sha256": {"okx_l2_archive": row["raw_archive_sha256"]},
                    "execution_basis": "official_okx_sampled_l2_best_bbo",
                    "data_quality": "ok",
                    "feature_weights": (
                        {"depth_imbalance": 0.5, "momentum": 0.5}
                        if feature_mode == "combined" else {feature_mode: 1.0}
                    ),
                    "feature_value": feature_value,
                },
            })
            target = next_state
            signals += 1
            linked_observations += 1
        active.marks["BTC-USDT"] = (float(row["best_bid"]) + float(row["best_ask"])) / 2.0
        await service._record_equity(active)
        throttle.pause()

    # Close any live exposure using the final real BBO, never a synthetic close.
    if target != 0:
        row = rows[-1]
        observed_at = datetime.fromisoformat(row["event_at"])
        clock.current = observed_at
        observation_id = f"okx-l2:{row['event_ts_ms']}:close"
        observation = await service.record_quote_observation(
            run_id, observation_id=observation_id, instrument_id="BTC-USDT",
            observed_at=row["event_at"], bid=float(row["best_bid"]),
            ask=float(row["best_ask"]), bid_depth=float(row["bid_depth_top20"]),
            ask_depth=float(row["ask_depth_top20"]), source=str(row["source"]),
            raw_payload_sha256=str(row["raw_archive_sha256"]),
            sequence_id=str(row["event_ts_ms"]),
            metadata={"history_scope": "historical_orderbook_sampled", "close": True},
        )
        await service._dispatch("features.snapshots", {
            "market_id": "BTC-USDT", "timestamp": observed_at,
            "mid": (float(row["best_bid"]) + float(row["best_ask"])) / 2.0,
            "bid": float(row["best_bid"]), "ask": float(row["best_ask"]),
            "bid_depth": float(row["bid_depth_top20"]),
            "ask_depth": float(row["ask_depth_top20"]), "target": 0.0,
            "previous_target": target, "position_fraction": 0.0,
            "signal_meta": {
                "source": "okx_l2_imbalance_replay", "quote_source": str(row["source"]),
                "quote_observation_id": observation["observation_id"],
                "raw_sha256": {"okx_l2_archive": row["raw_archive_sha256"]},
                "execution_basis": "official_okx_sampled_l2_best_bbo_close",
                "data_quality": "ok", "feature_weights": {"depth_imbalance": 1.0},
            },
        })
        signals += 1
        linked_observations += 1
        active.marks["BTC-USDT"] = (float(row["best_bid"]) + float(row["best_ask"])) / 2.0
        await service._record_equity(active)

    await service.stop_run(run_id)
    equity_points = service.store.list_equity_points(run_id)
    independent_days = sorted({str(point.ts)[:10] for point in equity_points})
    last_equity_by_day: dict[str, float] = {}
    for point in equity_points:
        last_equity_by_day[str(point.ts)[:10]] = float(point.equity)
    daily_returns: dict[str, float] = {}
    previous_equity = 10_000.0
    for day in independent_days:
        close_equity = last_equity_by_day[day]
        daily_returns[day] = close_equity / previous_equity - 1.0
        previous_equity = close_equity
    metrics = sim_metrics.compute_run_metrics(service.store, run_id)
    blockers = [
        "sampled 1-second L2, not venue fill-by-fill execution",
        "no capacity/partial-fill model beyond top-20 depth snapshot",
    ]
    if len(independent_days) < 20:
        blockers.append("fewer than 20 independent trading days")
    if len(independent_days) < 20:
        blockers.append("independent out-of-sample and 12 complete months unavailable")
    if float(metrics.get("win_rate") or 0.0) <= 0.80:
        blockers.append("cost-after win rate is not above 80%")
    result = {
        "real_data_only": True,
        "strategy": f"okx_l2_{feature_mode}_stateful",
        "instrument": "BTC-USDT",
        "run_id": run_id,
        "rows_used": len(rows),
        "coverage": {
            "start": rows[0]["event_at"], "end": rows[-1]["event_at"],
            "independent_days": len(independent_days),
            "days": independent_days,
            "daily_returns": daily_returns,
        },
        "signals": signals,
        "linked_observations": linked_observations,
        "source": "www.okx.com_historical_l2",
        "history_scope": "historical_orderbook_sampled",
        "parameters": {
            "enter": enter, "exit": exit,
            "position_fraction": position_fraction,
            "impact_coefficient": impact_coefficient,
            "invert_signal": invert_signal,
            "feature_mode": feature_mode,
            "lookback_rows": lookback_rows,
            "momentum_enter": momentum_enter,
            "momentum_exit": momentum_exit,
            "sample_seconds": None,
        },
        "metrics": metrics,
        "status": "diagnostic_not_promotion",
        "promotion_blockers": blockers,
        "database": str(db_path),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    return result


async def main_async(
    dataset: Path, output: Path, output_dir: Path, sample_seconds: int,
    position_fraction: float, impact_coefficient: float, enter: float, exit: float,
    invert_signal: bool, feature_mode: str, lookback_rows: int,
    momentum_enter: float, momentum_exit: float,
) -> None:
    rows = load_quotes(dataset, sample_seconds=sample_seconds)
    result = await replay(
        rows, output_dir, position_fraction=position_fraction,
        impact_coefficient=impact_coefficient,
        enter=enter, exit=exit,
        invert_signal=invert_signal,
        feature_mode=feature_mode, lookback_rows=lookback_rows,
        momentum_enter=momentum_enter, momentum_exit=momentum_exit,
    )
    result["dataset"] = str(dataset)
    result["parameters"]["sample_seconds"] = sample_seconds
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=Path("data/okx_l2_imbalance_replay.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/.kernel_replay_okx_l2"))
    parser.add_argument("--sample-seconds", type=int, default=5)
    parser.add_argument("--position-fraction", type=float, default=0.10)
    parser.add_argument("--impact-coefficient", type=float, default=0.10)
    parser.add_argument("--enter", type=float, default=0.65)
    parser.add_argument("--exit", type=float, default=0.15)
    parser.add_argument("--invert-signal", action="store_true")
    parser.add_argument("--feature-mode", choices=("depth_imbalance", "momentum", "combined"), default="depth_imbalance")
    parser.add_argument("--lookback-rows", type=int, default=4)
    parser.add_argument("--momentum-enter", type=float, default=50.0)
    parser.add_argument("--momentum-exit", type=float, default=10.0)
    args = parser.parse_args()
    asyncio.run(main_async(
        args.dataset, args.output, args.output_dir, args.sample_seconds,
        args.position_fraction, args.impact_coefficient, args.enter, args.exit,
        args.invert_signal, args.feature_mode, args.lookback_rows,
        args.momentum_enter, args.momentum_exit,
    ))
