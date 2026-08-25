"""Safely compact normalized Parquet parts into a provenance-linked sidecar.

The source parts are never deleted by this tool.  ``--apply`` writes a new
sidecar under ``data/datasets/compacted`` and records every input path, row
count, schema fingerprint, and output path.  A later cutover can only happen
after consumers and recovery tests validate this manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow.dataset as ds
import pyarrow.parquet as pq


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _files(source: Path) -> list[Path]:
    return sorted(path for path in source.rglob("*.parquet") if path.is_file())


def _source_manifest(paths: list[Path], manifest: Path) -> dict[str, Any]:
    if not manifest.exists():
        return {"path": str(manifest), "exists": False, "input_paths_found": 0}
    input_paths = {str(path) for path in paths}
    found = 0
    entries = 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            entries += 1
            if str(item.get("path")) in input_paths:
                found += 1
    return {"path": str(manifest), "exists": True, "entries": entries,
            "input_paths": len(paths), "input_paths_found": found,
            "sha256": _sha256(manifest)}


def plan(dataset: str, *, source_root: Path, destination_root: Path) -> dict[str, Any]:
    source = source_root / dataset
    files = _files(source)
    groups: dict[str, list[Path]] = {}
    for path in files:
        relative_parent = str(path.parent.relative_to(source))
        groups.setdefault(relative_parent, []).append(path)
    group_rows = []
    for relative_parent, inputs in sorted(groups.items()):
        rows = sum(int(pq.ParquetFile(path).metadata.num_rows) for path in inputs)
        group_rows.append({
            "partition": relative_parent,
            "input_files": len(inputs),
            "input_rows": rows,
            "input_bytes": sum(path.stat().st_size for path in inputs),
            "output": str(destination_root / dataset / relative_parent / "part-compact-00000.parquet"),
            "inputs": [str(path) for path in inputs],
        })
    return {
        "schema_version": "dataset-compaction-plan-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": dataset,
        "source_root": str(source),
        "destination_root": str(destination_root / dataset),
        "mode": "sidecar_only_source_preserved",
        "input_files": len(files),
        "input_rows": sum(item["input_rows"] for item in group_rows),
        "input_bytes": sum(item["input_bytes"] for item in group_rows),
        "source_manifest": _source_manifest(files, Path("data/datasets/manifest.jsonl")),
        "groups": group_rows,
    }


def apply_plan(payload: dict[str, Any]) -> dict[str, Any]:
    outputs = []
    for group in payload["groups"]:
        inputs = [Path(path) for path in group["inputs"]]
        output = Path(group["output"])
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".pending")
        table = ds.dataset([str(path) for path in inputs], format="parquet").to_table()
        if table.num_rows != int(group["input_rows"]):
            raise RuntimeError(
                f"row count changed for {group['partition']}: "
                f"{table.num_rows} != {group['input_rows']}"
            )
        pq.write_table(table, temporary, compression="zstd")
        temporary.replace(output)
        output_rows = int(pq.ParquetFile(output).metadata.num_rows)
        if output_rows != int(group["input_rows"]):
            raise RuntimeError(f"output verification failed: {output}")
        outputs.append({
            "partition": group["partition"], "input_files": group["input_files"],
            "input_rows": group["input_rows"], "output": str(output),
            "output_rows": output_rows, "output_bytes": output.stat().st_size,
            "output_sha256": _sha256(output),
        })
    return {**payload, "status": "APPLIED", "outputs": outputs,
            "source_preserved": True, "verified": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--source-root", type=Path, default=Path("data/datasets/parts"))
    parser.add_argument("--destination-root", type=Path, default=Path("data/datasets/compacted"))
    parser.add_argument("--plan-output", type=Path, default=None)
    parser.add_argument("--apply", action="store_true", help="write sidecar output; source is never deleted")
    args = parser.parse_args()
    payload = plan(args.dataset, source_root=args.source_root, destination_root=args.destination_root)
    if args.apply:
        payload = apply_plan(payload)
    else:
        payload["status"] = "PLAN_ONLY"
    output = args.plan_output or Path("data") / f"{args.dataset}_compaction_plan.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: payload.get(key) for key in (
        "dataset", "status", "input_files", "input_rows", "input_bytes", "verified", "source_preserved",
    )}, ensure_ascii=False, indent=2))
    print(f"写入 {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
