"""Build a fail-closed per-instrument strategy evidence artifact.

This is a reporting step, not a promotion command. It joins already completed
real-data replays without inventing a denominator for shared portfolio PnL or
turning missing execution/target evidence into a pass.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ANNUAL_TARGET = 0.50
MONTHLY_TARGET = 0.15


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _target_status(result: dict[str, Any]) -> str:
    target = result.get("return_target")
    if not isinstance(target, dict):
        return "UNKNOWN"
    status = str(target.get("status", "UNKNOWN"))
    return status if status in {"PASS", "FAIL", "UNKNOWN"} else "UNKNOWN"


def _standalone(path: Path) -> list[dict[str, Any]]:
    report = _read(path)
    output = []
    for result in report.get("results", []):
        if not isinstance(result, dict) or not result.get("symbol"):
            continue
        metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
        output.append({
            "instrument": str(result["symbol"]),
            "domain": str(result.get("domain", "unknown")),
            "strategy": str(report.get("signal_contract", {}).get("strategy_id", path.stem)),
            "source": str(path),
            "total_return": metrics.get("total_return"),
            "max_drawdown": metrics.get("max_drawdown"),
            "sharpe": metrics.get("sharpe"),
            "closed_trade_count": metrics.get("closed_trade_count"),
            "oos_return": None,
            "annualized_return": (result.get("return_target") or {}).get("annualized_return"),
            "monthly_target_status": _target_status(result),
            "stability_status": (result.get("stability") or {}).get("status", "UNKNOWN"),
            "execution_evidence": result.get("execution_evidence", {}),
            "promotion": result.get("promotion", "UNKNOWN"),
            "promotion_reason": result.get("promotion_reason", "unknown"),
        })
    return output


def _crypto_multifold(path: Path) -> list[dict[str, Any]]:
    report = _read(path)
    folds = [fold for fold in report.get("folds", []) if isinstance(fold, dict)]
    if not folds:
        return []
    latest = folds[-1]
    output = []
    for result in latest.get("results", []):
        if not isinstance(result, dict) or not result.get("symbol"):
            continue
        metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
        output.append({
            "instrument": str(result["symbol"]),
            "domain": "crypto",
            "strategy": str(report.get("strategy", {}).get("family", path.stem)),
            "source": str(path),
            "fold": str(latest.get("split_date")),
            "total_return": metrics.get("total_return"),
            "max_drawdown": metrics.get("max_drawdown"),
            "sharpe": metrics.get("sharpe"),
            "closed_trade_count": result.get("oos_closed_trades"),
            "oos_return": result.get("oos_return"),
            "oos_excess_return": result.get("excess_oos_return"),
            "annualized_return": None,
            "monthly_target_status": "UNKNOWN",
            "stability_status": "UNKNOWN",
            "execution_evidence": metrics.get("execution_evidence", {}),
            "promotion": "BLOCKED",
            "promotion_reason": "annual/monthly target and stability evidence unavailable",
        })
    return output


def _crypto_walk_forward(path: Path) -> list[dict[str, Any]]:
    report = _read(path)
    folds = [fold for fold in report.get("folds", []) if isinstance(fold, dict)]
    if not folds:
        return []
    latest = folds[-1]
    output = []
    for result in latest.get("results", []):
        if not isinstance(result, dict) or not result.get("symbol"):
            continue
        metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
        output.append({
            "instrument": str(result["symbol"]),
            "domain": "crypto",
            "strategy": "walk_forward_time_series_momentum",
            "source": str(path),
            "fold": str(latest.get("split_date")),
            "selected_candidate": latest.get("selected_candidate"),
            "total_return": metrics.get("total_return"),
            "max_drawdown": metrics.get("max_drawdown"),
            "sharpe": metrics.get("sharpe"),
            "closed_trade_count": result.get("oos_closed_trades"),
            "oos_return": result.get("oos_return"),
            "oos_excess_return": result.get("excess_oos_return"),
            "annualized_return": None,
            "monthly_target_status": "UNKNOWN",
            "stability_status": "UNKNOWN",
            "execution_evidence": metrics.get("execution_evidence", {}),
            "promotion": "BLOCKED",
            "promotion_reason": "walk-forward increment lacks full monthly/stability/depth gates",
        })
    return output


def _deep_drawdown_kernel(path: Path) -> list[dict[str, Any]]:
    """Flatten per-symbol drawdown kernel cases without averaging away risk."""
    report = _read(path)
    output = []
    for result in report.get("results", []):
        if not isinstance(result, dict) or not result.get("symbol"):
            continue
        metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
        target = metrics.get("return_target") if isinstance(metrics.get("return_target"), dict) else {}
        event_stats = result.get("event_stats") if isinstance(result.get("event_stats"), dict) else {}
        oos = event_stats.get("oos") if isinstance(event_stats.get("oos"), dict) else {}
        target_status = (
            _target_status(metrics)
            if result.get("events") and int(oos.get("n_complete") or 0) > 0
            else "UNKNOWN"
        )
        output.append({
            "instrument": str(result["symbol"]),
            "domain": str(result.get("domain", "unknown")),
            "strategy": "deep_drawdown_rebound_v1",
            "source": str(path),
            "hold_days": result.get("hold_days"),
            "cost_multiple": result.get("cost_multiple"),
            "total_return": metrics.get("total_return"),
            "max_drawdown": metrics.get("max_drawdown"),
            "sharpe": metrics.get("sharpe"),
            "closed_trade_count": metrics.get("closed_trade_count"),
            "oos_return": oos.get("mean_net_return"),
            "annualized_return": target.get("annualized_return"),
            "monthly_target_status": target_status,
            "stability_status": str(oos.get("status", "UNKNOWN")),
            "execution_evidence": metrics.get("execution_evidence", {}),
            "promotion": result.get("promotion", "BLOCKED"),
            "promotion_reason": "deep-drawdown PIT, survivorship and executable quote gates remain unresolved",
            "event_stats": event_stats,
        })
    return output


def build_evidence(root: Path) -> dict[str, Any]:
    sources = [
        root / "data/cross_sectional_standalone_us_oos_candidate_20_30_5.json",
        root / "data/cross_sectional_standalone_a_oos_candidate_20_30_5.json",
        root / "data/crypto_tsmom_multifold_replay.json",
        root / "data/crypto_tsmom_walk_forward_replay.json",
    ]
    optional_sources = [
        root / "data/cross_sectional_six_frozen_2022.json",
        root / "data/cross_sectional_six_breadth05_2022.json",
        root / "data/cross_sectional_six_meanrev20_100_2022.json",
        root / "data/deep_drawdown_kernel_replay.json",
        root / "data/deep_drawdown_kernel_quality_confirm5.json",
    ]
    missing = [str(path) for path in sources if not path.exists()]
    optional_missing = [str(path) for path in optional_sources if not path.exists()]
    rows: list[dict[str, Any]] = []
    if not missing:
        rows.extend(_standalone(sources[0]))
        rows.extend(_standalone(sources[1]))
        rows.extend(_crypto_multifold(sources[2]))
        rows.extend(_crypto_walk_forward(sources[3]))
        for path in optional_sources:
            if path.exists():
                if path.name.startswith("cross_sectional_six_"):
                    rows.extend(_standalone(path))
                else:
                    rows.extend(_deep_drawdown_kernel(path))

    by_instrument: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_instrument.setdefault(row["instrument"], []).append(row)
    for values in by_instrument.values():
        values.sort(key=lambda row: (row["strategy"], row.get("fold", "")))

    counts = {"PASS": 0, "FAIL": 0, "UNKNOWN": 0}
    for row in rows:
        counts[row["monthly_target_status"]] = counts.get(row["monthly_target_status"], 0) + 1
    return {
        "schema_version": "instrument-strategy-evidence-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "real_data_only": True,
        "research_only": True,
        "target_contract": {
            "annualized_return_min": ANNUAL_TARGET,
            "monthly_return_min": MONTHLY_TARGET,
            "missing_is_not_pass": True,
        },
        "sources": [str(path) for path in (*sources, *optional_sources)],
        "missing_sources": [*missing, *optional_missing],
        "instrument_count": len(by_instrument),
        "evidence_row_count": len(rows),
        "target_status_counts": counts,
        "instruments": by_instrument,
        "promotion": "BLOCKED",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=Path("data/instrument_strategy_evidence.json"))
    args = parser.parse_args()
    report = build_evidence(args.root)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "instrument_count", "evidence_row_count", "target_status_counts", "promotion",
    )}, ensure_ascii=False, indent=2))
    print(f"写入 {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
