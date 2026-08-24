"""Create fail-closed lineage manifests for the BTC 5m companion reports."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from libs.data.run_manifest import _code_state


REPORTS = {
    "calibration": Path("data/btc5m_calibration.json"),
    "direction_kernel_replay": Path("data/btc5m_direction_kernel_replay.json"),
    "event_kernel_replay": Path("data/btc5m_event_kernel_replay.json"),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dataset_files(report: dict[str, Any]) -> list[Path]:
    value = report.get("dataset")
    if not value:
        return []
    path = Path(str(value))
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(path.rglob("*.parquet"))
    return []


def build_manifest(name: str, report_path: Path) -> dict[str, Any]:
    report = json.loads(report_path.read_text())
    files = _dataset_files(report)
    date_values = [
        str(row.get("date"))
        for row in (report.get("rows") if isinstance(report.get("rows"), list) else [])
        if isinstance(row, dict) and row.get("date")
    ]
    dataset_hash = hashlib.sha256()
    for path in files:
        dataset_hash.update(str(path).encode())
        dataset_hash.update(_sha256(path).encode())
    return {
        "schema_version": "btc5m-report-lineage-v1",
        "report_name": name,
        "report_path": str(report_path),
        "report_sha256": _sha256(report_path),
        "generated_at": datetime.now(UTC).isoformat(),
        "source_generated_at": report.get("generated_at"),
        "code": _code_state(),
        "reproducible": bool(_code_state().get("commit") and not _code_state().get("dirty")),
        "real_data_only": bool(report.get("real_data_only")),
        "pit_status": "UNKNOWN",
        "tradable_evidence": bool(report.get("tradable_evidence", False)),
        "dataset_paths": [str(path) for path in files],
        "dataset_sha256": dataset_hash.hexdigest() if files else None,
        "date_range": {
            "first": min(date_values) if date_values else None,
            "last": max(date_values) if date_values else None,
        },
        "parameters": {
            key: report[key]
            for key in ("thresholds", "cost_multiples", "edge_threshold", "spread_bps")
            if key in report
        },
        "degradation": {
            "status": "diagnostic_only" if report.get("tradable_evidence") is False else "UNKNOWN",
            "reason": report.get("execution_basis") or "historical report lacks strict PIT contract",
        },
    }


def main() -> int:
    for name, report_path in REPORTS.items():
        if not report_path.exists():
            raise FileNotFoundError(report_path)
        output = report_path.with_name(f"{report_path.stem}.manifest.json")
        output.write_text(json.dumps(build_manifest(name, report_path), ensure_ascii=False, indent=2) + "\n")
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
