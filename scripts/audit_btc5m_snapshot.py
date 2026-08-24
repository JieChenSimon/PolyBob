"""Fail-closed audit for a BTC 5m research snapshot.

This is deliberately a read-only gate.  It does not rewrite reports, deduplicate
the lake, or infer an OOS result.  A report is trustworthy only when the report,
manifest, checkpoint, and normalized parquet dataset describe the same unique
windows and the manifest contains an explicit OOS boundary.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pyarrow.dataset as ds


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _sample_keys(checkpoint: dict[str, Any]) -> set[int]:
    return {
        int(sample["window_start"])
        for sample in checkpoint.get("samples", [])
        if isinstance(sample, dict) and "window_start" in sample
    }


def _dataset_keys(path: Path) -> tuple[list[dict[str, Any]], set[int]]:
    rows = ds.dataset(path, format="parquet").to_table().to_pylist()
    return rows, {int(row["window_start"]) for row in rows}


def audit(
    report_path: Path,
    manifest_path: Path,
    checkpoint_path: Path,
    dataset_path: Path,
) -> dict[str, Any]:
    report = _load(report_path)
    manifest = _load(manifest_path)
    checkpoint = _load(checkpoint_path)
    rows, dataset_keys = _dataset_keys(dataset_path)

    report_result = report.get("result") or {}
    report_windows = int(report.get("n_windows", 0))
    report_trades = int(report_result.get("n", 0))
    manifest_inputs = manifest.get("inputs", {}).get("polymarket_windows", {})
    checkpoint_keys = _sample_keys(checkpoint)
    row_keys = [int(row["window_start"]) for row in rows]
    row_key_counts: dict[int, int] = {}
    for key in row_keys:
        row_key_counts[key] = row_key_counts.get(key, 0) + 1
    duplicate_keys = sorted(key for key, count in row_key_counts.items() if count > 1)

    checks = {
        "report_manifest_windows": (
            report_windows == int(manifest_inputs.get("settled", -1))
        ),
        "report_manifest_trades": (
            report_trades == int(manifest_inputs.get("qualifying_trades", -1))
        ),
        "checkpoint_spec_v6": str(checkpoint.get("spec", "")).startswith("btc5m-v6-"),
        "report_checkpoint_windows": report_windows == len(checkpoint_keys),
        "checkpoint_dataset_windows": checkpoint_keys == dataset_keys,
        "dataset_unique_windows": not duplicate_keys and len(rows) == len(dataset_keys),
        "explicit_oos_boundary": bool(
            manifest.get("oos_start")
            or manifest.get("params", {}).get("oos_start")
            or report.get("oos_start")
        ),
    }

    status = "PASS" if all(checks.values()) else "UNKNOWN"
    return {
        "status": status,
        "checks": checks,
        "counts": {
            "report_windows": report_windows,
            "report_qualifying_trades": report_trades,
            "manifest_settled": manifest_inputs.get("settled"),
            "manifest_qualifying_trades": manifest_inputs.get("qualifying_trades"),
            "checkpoint_windows": len(checkpoint_keys),
            "dataset_rows": len(rows),
            "dataset_unique_windows": len(dataset_keys),
            "duplicate_window_count": len(duplicate_keys),
        },
        "oos": {
            "status": "AVAILABLE" if checks["explicit_oos_boundary"] else "UNKNOWN",
            "reason": None if checks["explicit_oos_boundary"] else "missing explicit OOS boundary",
        },
        "paths": {
            "report": str(report_path),
            "manifest": str(manifest_path),
            "checkpoint": str(checkpoint_path),
            "dataset": str(dataset_path),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=Path("data/btc5m_mispricing.json"))
    parser.add_argument("--manifest", type=Path, default=Path("data/btc5m_mispricing.manifest.json"))
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=Path("data/market_cache/btc5m/collection_checkpoint.json"),
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("data/datasets/parts/btc5m_settled_windows_v6/symbol=BTC-USDT"),
    )
    args = parser.parse_args()
    result = audit(args.report, args.manifest, args.checkpoint, args.dataset)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
