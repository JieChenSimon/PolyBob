"""Create a low-impact, provenance-aware data layout inventory.

The default mode reads directory metadata only.  It never deletes, rewrites,
or hashes every byte on disk; exact duplicate hashing is an explicit future
step after metadata groups have been reviewed.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SMALL_FILE_BYTES = 64 * 1024
DEFAULT_ROOTS = (
    Path("data/store"), Path("data/market_cache"), Path("data/datasets"),
    Path("data/.kernel_replay_insider"),
)


def _kind(path: Path) -> str:
    parts = path.parts
    if "market_cache" in parts:
        return "cache"
    if "datasets" in parts:
        if "raw" in parts:
            return "raw_evidence"
        if "parts" in parts:
            return "normalized"
        return "datasets_other"
    if any(part.startswith(".kernel_replay") for part in parts):
        return "replay_tmp"
    if "store" in parts:
        return "store"
    return "other"


def _walk(paths: tuple[Path, ...]) -> list[tuple[Path, int]]:
    rows: list[tuple[Path, int]] = []
    for root in paths:
        if not root.exists():
            continue
        for directory, _dirs, files in os.walk(root):
            base = Path(directory)
            for name in files:
                path = base / name
                try:
                    rows.append((path, path.stat().st_size))
                except FileNotFoundError:
                    # A concurrent cache writer may have atomically replaced a
                    # file between os.walk and stat; it is recorded as absent.
                    continue
    return rows


def _manifest_audit(manifest: Path) -> dict[str, Any]:
    if not manifest.exists():
        return {"path": str(manifest), "exists": False, "entries": 0,
                "path_entries": 0, "existing_paths": 0, "missing_paths": 0}
    entries: list[dict[str, Any]] = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            entries.append(value)
    paths = [Path(str(item["path"])) for item in entries if item.get("path")]
    existing = sum(path.exists() for path in paths)
    return {"path": str(manifest), "exists": True, "entries": len(entries),
            "path_entries": len(paths), "existing_paths": existing,
            "missing_paths": len(paths) - existing}


def audit(paths: tuple[Path, ...] = DEFAULT_ROOTS, *, manifest: Path = Path("data/datasets/manifest.jsonl")) -> dict[str, Any]:
    files = _walk(paths)
    by_kind: dict[str, dict[str, Any]] = {}
    duplicate_groups: Counter[tuple[str, int, str]] = Counter()
    for path, size in files:
        kind = _kind(path)
        item = by_kind.setdefault(kind, {
            "files": 0, "bytes": 0, "small_files_lt_64k": 0,
            "extensions": {},
        })
        item["files"] += 1
        item["bytes"] += size
        item["small_files_lt_64k"] += int(size < SMALL_FILE_BYTES)
        extension = path.suffix.lower() or "[none]"
        item["extensions"][extension] = item["extensions"].get(extension, 0) + 1
        duplicate_groups[(kind, size, extension)] += 1
    candidates = [
        {"kind": kind, "size": size, "extension": extension, "files": count}
        for (kind, size, extension), count in sorted(duplicate_groups.items())
        if count > 1
    ]
    return {
        "schema_version": "data-layout-audit-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "metadata_only_no_delete_no_full_hash",
        "roots": [str(path) for path in paths],
        "small_file_threshold_bytes": SMALL_FILE_BYTES,
        "total_files": len(files),
        "total_bytes": sum(size for _path, size in files),
        "by_kind": by_kind,
        "manifest": _manifest_audit(manifest),
        "duplicate_analysis": {
            "exact_hash_duplicates_confirmed": 0,
            "metadata_candidate_group_count": len(candidates),
            "metadata_candidate_file_count": sum(item["files"] for item in candidates),
            "candidates": candidates[:1000],
            "reason": "same size and extension is not proof of duplicate content",
        },
        "retention_classes": {
            "raw_evidence": "immutable_keep_with_provenance",
            "normalized": "rebuildable_keep_manifest_and_pit",
            "cache": "bounded_ttl_rebuildable",
            "replay_tmp": "delete_only_after_checkpoint_and_shutdown_audit",
            "store": "canonical_query_layer_keep_until_migration_verified",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/data_layout_audit.json"))
    args = parser.parse_args()
    report = audit()
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("total_files", "total_bytes", "by_kind", "manifest", "duplicate_analysis")}, ensure_ascii=False, indent=2))
    print(f"写入 {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
