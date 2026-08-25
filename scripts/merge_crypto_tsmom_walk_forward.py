"""Merge independently completed crypto walk-forward fold artifacts."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def merge(paths: list[Path]) -> dict[str, Any]:
    if not paths:
        raise ValueError("at least one fold artifact is required")
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    first = reports[0]
    folds = []
    seen: set[str] = set()
    for report in reports:
        if report.get("candidate_grid") != first.get("candidate_grid"):
            raise ValueError("candidate grids differ")
        if report.get("symbols") != first.get("symbols"):
            raise ValueError("symbol counts differ")
        for fold in report.get("folds", []):
            split = str(fold.get("split_date"))
            if split in seen:
                raise ValueError(f"duplicate fold: {split}")
            seen.add(split)
            folds.append(fold)
    folds.sort(key=lambda fold: str(fold["split_date"]))
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "real_data_only": True,
        "execution_kernel": first.get("execution_kernel"),
        "candidate_grid": first.get("candidate_grid"),
        "execution_config": first.get("execution_config"),
        "symbols": first.get("symbols"),
        "quality_rejected": first.get("quality_rejected"),
        "folds": folds,
        "selection_is_train_only": True,
        "oos_execution_capital": first.get("oos_execution_capital"),
        "latest_fold_only": False,
        "source_artifacts": [str(path) for path in paths],
        "status": "replay_only_not_promoted",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("folds", type=Path, nargs="+")
    args = parser.parse_args()
    report = merge(args.folds)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    print(json.dumps({"folds": [f["split_date"] for f in report["folds"]],
                      "status": report["status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
