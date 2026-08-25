"""Replay a stateful BTC 5m probability strategy through the real kernel.

This is a separately versioned candidate: it keeps the probability model fixed
and imposes a minimum holding period to test whether the prior candidate's
failure was dominated by turnover. It does not overwrite the original
per-window probability evidence.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from libs.quant.promotion import PromotionGate
from scripts.btc5m_direction_kernel_replay import (
    COSTS,
    DATASET,
    SPLITS,
    THRESHOLDS,
    load_windows,
    replay,
)

MIN_HOLD_WINDOWS = 12


def stateful_targets(rows: list[dict], threshold: float, hold_windows: int = MIN_HOLD_WINDOWS) -> list[float]:
    """Hold a non-zero direction for at least ``hold_windows`` observations."""
    if hold_windows < 1:
        raise ValueError("hold_windows must be positive")
    target = 0.0
    remaining = 0
    targets: list[float] = []
    for row in rows:
        desired = (
            0.10 if row["probability"] >= threshold
            else (-0.10 if row["probability"] <= 1.0 - threshold else 0.0)
        )
        if remaining > 0:
            remaining -= 1
            desired = target
        if desired != target:
            target = desired
            if target != 0.0:
                remaining = hold_windows
        targets.append(target)
    return targets


def stateful_target_pairs(rows: list[dict], threshold: float) -> list[tuple[float, float]]:
    """Keep the stateful target at each window exit instead of forcing flat."""
    targets = stateful_targets(rows, threshold)
    return list(zip(targets, targets))


def _worker(args: tuple[list[dict], float, str, float, Path]) -> dict:
    rows, threshold, split, multiple, out_dir = args
    return asyncio.run(replay(
        rows, threshold, split, multiple, out_dir,
        target_builder=stateful_target_pairs,
    ))


def _write_progress(path: Path, completed: int, total: int, started: float, current: str | None = None) -> None:
    elapsed = max(0.0, time.monotonic() - started)
    rate = completed / elapsed if elapsed else 0.0
    eta = (total - completed) / rate if rate else None
    path.write_text(json.dumps({
        "status": "completed" if completed == total else "running",
        "completed": completed, "total": total,
        "fraction": completed / total if total else 1.0,
        "elapsed_seconds": round(elapsed, 3),
        "eta_seconds": round(eta, 3) if eta is not None else None,
        "current": current,
        "updated_at": datetime.now(UTC).isoformat(),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"stateful replay progress {completed}/{total} current={current or '-'}", flush=True)


async def main_async() -> int:
    rows = load_windows()
    dates = [row["date"] for row in rows]
    splits = [dates[int(len(dates) * fraction)] for fraction in SPLITS]
    out_dir = Path("data/.kernel_replay_btc5m_stateful_direction")
    out_dir.mkdir(parents=True, exist_ok=True)
    progress = out_dir / "progress.json"
    total = len(THRESHOLDS) * len(splits) * len(COSTS)
    started = time.monotonic()
    _write_progress(progress, 0, total, started)
    workers = max(1, min(4, int(os.environ.get("POLYBOB_REPLAY_WORKERS", "4"))))
    loop = asyncio.get_running_loop()
    jobs = [
        (rows, threshold, split, multiple, out_dir)
        for threshold in THRESHOLDS for split in splits for multiple in COSTS
    ]
    completed: dict[tuple[float, str, float], dict] = {}
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [loop.run_in_executor(pool, functools.partial(_worker, job)) for job in jobs]
        for job, future in zip(jobs, futures):
            result = await future
            _, threshold, split, multiple, _ = job
            completed[(threshold, split, multiple)] = result
            _write_progress(progress, len(completed), total, started,
                            f"threshold={threshold} split={split} cost={multiple}")
    results: dict[str, object] = {}
    for threshold in THRESHOLDS:
        folds = []
        for split in splits:
            folds.append({"split_date": split, "costs": [completed[(threshold, split, multiple)] for multiple in COSTS]})
        base = [float(fold["costs"][0]["oos_return"]) for fold in folds if fold["costs"][0]["oos_return"] is not None]
        stability = sum(value > 0 for value in base) / len(base) if base else 0.0
        gate_returns = list(folds[0]["costs"][0].get("oos_daily_returns") or [])
        gate = PromotionGate(n_trials=len(THRESHOLDS) * len(COSTS), min_dsr=.90,
                             min_observations=200, min_oos_stability_rate=.5,
                             cost_min_sharpe=.3).evaluate(
            gate_returns,
            cost_returns_fn=lambda multiple: list(
                folds[0]["costs"][COSTS.index(multiple)].get("oos_daily_returns") or []
            ),
            cost_multiples=COSTS, oos_stability_rate=stability,
        )
        results[str(threshold)] = {"folds": folds, "promotion": gate.to_dict()}
    report = {
        "schema_version": "btc5m-stateful-direction-kernel-replay-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "real_data_only": True, "research_only": True,
        "strategy": "btc5m_stateful_probability_direction",
        "base_strategy": "btc5m_spot_direction_proxy",
        "dataset": str(DATASET), "windows": len(rows),
        "min_hold_windows": MIN_HOLD_WINDOWS,
        "thresholds": list(THRESHOLDS), "cost_multiples": list(COSTS),
        "splits": splits, "workers": workers, "results": results,
        "promotion": {"status": "BLOCKED", "reason": "historical_depth_unknown_and_candidate_gate_failed"},
    }
    output = Path("data/btc5m_stateful_direction_kernel_replay.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    _write_progress(progress, total, total, started, "report_written")
    print(json.dumps({"output": str(output), "promotion": report["promotion"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
