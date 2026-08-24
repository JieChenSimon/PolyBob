"""Inventory and safely compact local data artifacts.

The command is intentionally non-destructive: inventory is read-only and
``compact --apply`` writes a new columnar dataset plus a provenance manifest.
It never replaces or deletes the source tree.  This keeps raw provider
evidence, PIT vintages and audit ledgers recoverable while allowing the query
layer to move from thousands of tiny Parquet payloads to a bounded set of
partitioned files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _file_inventory(root: Path) -> dict[str, Any]:
    by_extension: dict[str, dict[str, int]] = defaultdict(lambda: {"files": 0, "bytes": 0})
    by_top_level: dict[str, dict[str, int]] = defaultdict(lambda: {"files": 0, "bytes": 0})
    small_files = 0
    total_bytes = 0
    total_files = 0
    for path in root.rglob("*"):
        if not path.is_file() or path.name.startswith(".pending-"):
            continue
        size = path.stat().st_size
        extension = path.suffix.lower() or "[no_ext]"
        relative = path.relative_to(root)
        top_level = relative.parts[0] if relative.parts else "[root]"
        by_extension[extension]["files"] += 1
        by_extension[extension]["bytes"] += size
        by_top_level[top_level]["files"] += 1
        by_top_level[top_level]["bytes"] += size
        total_files += 1
        total_bytes += size
        small_files += size < 64 * 1024
    return {
        "root": str(root),
        "files": total_files,
        "bytes": total_bytes,
        "small_files_lt_64KiB": small_files,
        "by_extension": dict(sorted(by_extension.items())),
        "by_top_level": dict(sorted(by_top_level.items())),
    }


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def compact_dataset(
    source: Path,
    destination: Path,
    *,
    partition_by: tuple[str, ...],
    deduplicate_exact_rows: bool = False,
) -> dict[str, Any]:
    """Write a compacted copy using DuckDB; never mutates ``source``."""
    import duckdb

    files = sorted(str(path) for path in source.rglob("*.parquet") if path.is_file())
    if not files:
        return {"status": "empty", "source": str(source), "files": 0}
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(
            f"refusing to write into non-empty destination: {destination}; choose a new run directory"
        )
    destination.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(":memory:")
    try:
        # A list avoids relying on a glob expansion limit and makes the exact
        # source set part of the reproducible run manifest.
        file_sql = "[" + ",".join(_sql_string(path) for path in files) + "]"
        connection.execute(
            "CREATE VIEW source_rows AS SELECT * FROM read_parquet(" + file_sql +
            ", union_by_name=true, hive_partitioning=true)"
        )
        count = int(connection.execute("SELECT count(*) FROM source_rows").fetchone()[0])
        relation = "SELECT DISTINCT * FROM source_rows" if deduplicate_exact_rows else "SELECT * FROM source_rows"
        partition_sql = ""
        if partition_by:
            partition_sql = ", PARTITION_BY (" + ",".join(partition_by) + ")"
        output = destination / "dataset"
        connection.execute(
            f"COPY ({relation}) TO {_sql_string(str(output))} "
            f"(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000{partition_sql})"
        )
        output_files = sorted(str(path) for path in destination.rglob("*.parquet"))
        output_bytes = sum(Path(path).stat().st_size for path in output_files)
        schema = connection.execute("DESCRIBE source_rows").fetchall()
        schema_hash = hashlib.sha256(
            json.dumps(schema, ensure_ascii=False, default=str, sort_keys=True).encode()
        ).hexdigest()
        manifest = {
            "status": "written",
            "source": str(source),
            "source_files": len(files),
            "source_rows": count,
            "destination": str(destination),
            "output_files": len(output_files),
            "output_bytes": output_bytes,
            "partition_by": list(partition_by),
            "deduplicate_exact_rows": deduplicate_exact_rows,
            "schema_sha256": schema_hash,
            "source_file_list_sha256": hashlib.sha256("\n".join(files).encode()).hexdigest(),
        }
        (destination / "compaction_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return manifest
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    inventory = sub.add_parser("inventory")
    inventory.add_argument("--root", default="data")
    inventory.add_argument("--output", default=None)
    compact = sub.add_parser("compact")
    compact.add_argument("--source", required=True)
    compact.add_argument("--destination", required=True)
    compact.add_argument("--partition-by", default="symbol")
    compact.add_argument("--deduplicate-exact-rows", action="store_true")
    compact.add_argument("--apply", action="store_true",
                         help="write the new dataset; without this flag only print the plan")
    args = parser.parse_args()
    if args.command == "inventory":
        result = _file_inventory(Path(args.root))
        payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            Path(args.output).write_text(payload, encoding="utf-8")
        else:
            print(payload, end="")
        return 0
    source = Path(args.source)
    destination = Path(args.destination)
    if not args.apply:
        result = _file_inventory(source)
        result.update({"status": "dry_run", "destination": str(destination),
                       "partition_by": [item for item in args.partition_by.split(",") if item]})
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    result = compact_dataset(
        source,
        destination,
        partition_by=tuple(item for item in args.partition_by.split(",") if item),
        deduplicate_exact_rows=args.deduplicate_exact_rows,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
