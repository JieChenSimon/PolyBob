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
from datetime import UTC, datetime
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _file_inventory(root: Path, *, top_level_limit: int = 50) -> dict[str, Any]:
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
    ranked = sorted(by_top_level.items(), key=lambda item: item[1]["bytes"], reverse=True)
    retained = dict(ranked[:max(0, top_level_limit)])
    omitted = ranked[max(0, top_level_limit):]
    return {
        "root": str(root),
        "files": total_files,
        "bytes": total_bytes,
        "small_files_lt_64KiB": small_files,
        "by_extension": dict(sorted(by_extension.items())),
        "by_top_level": retained,
        "omitted_top_level_groups": len(omitted),
        "omitted_top_level_files": sum(item[1]["files"] for item in omitted),
        "omitted_top_level_bytes": sum(item[1]["bytes"] for item in omitted),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parquet_detail(path: Path) -> dict[str, Any]:
    """Record per-file evidence needed before a source can be retired."""
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(path)
    schema_hash = hashlib.sha256(str(parquet.schema_arrow).encode("utf-8")).hexdigest()
    return {
        "path": str(path),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
        "rows": int(parquet.metadata.num_rows),
        "schema_sha256": schema_hash,
    }


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


_SQL_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _sql_identifier(value: str) -> str:
    if not _SQL_IDENTIFIER.fullmatch(value):
        raise ValueError(f"unsafe SQL identifier: {value!r}")
    return value


def compact_dataset(
    source: Path,
    destination: Path,
    *,
    partition_by: tuple[str, ...],
    deduplicate_exact_rows: bool = False,
    deduplicate_keys: tuple[str, ...] = (),
    latest_by: str | None = None,
) -> dict[str, Any]:
    """Write a compacted copy using DuckDB; never mutates ``source``."""
    import duckdb

    paths = sorted(path for path in source.rglob("*.parquet") if path.is_file())
    files = [str(path) for path in paths]
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
        if deduplicate_keys:
            keys = ",".join(_sql_identifier(value) for value in deduplicate_keys)
            order = f"{_sql_identifier(latest_by)} DESC NULLS LAST" if latest_by else "1"
            relation = (
                "SELECT * EXCLUDE (_rank) FROM ("
                "SELECT *, row_number() OVER ("
                f"PARTITION BY {keys} ORDER BY {order}"
                ") AS _rank FROM source_rows"
                ") WHERE _rank = 1"
            )
        else:
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
        source_details = [_parquet_detail(path) for path in paths]
        output_details = [_parquet_detail(Path(path)) for path in output_files]
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
            "deduplicate_keys": list(deduplicate_keys),
            "latest_by": latest_by,
            "schema_sha256": schema_hash,
            "source_file_list_sha256": hashlib.sha256("\n".join(files).encode()).hexdigest(),
            "source_file_details": source_details,
            "output_file_details": output_details,
            "retirement_status": "SOURCE_PRESERVED",
        }
        (destination / "compaction_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return manifest
    finally:
        connection.close()


def _validated_retirement(manifest_path: Path) -> tuple[dict[str, Any], list[Path], list[Path]]:
    """Validate exact source/output files before any retirement mutation."""
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_details = payload.get("source_file_details")
    output_details = payload.get("output_file_details")
    if payload.get("status") != "written" or payload.get("retirement_status") != "SOURCE_PRESERVED":
        raise RuntimeError("manifest is not an eligible source-preserved compaction")
    if not isinstance(source_details, list) or not source_details:
        raise RuntimeError("manifest lacks per-source file evidence")
    if not isinstance(output_details, list) or not output_details:
        raise RuntimeError("manifest lacks per-output file evidence")
    source_root = Path(payload["source"]).resolve()
    destination_root = Path(payload["destination"]).resolve()
    if source_root == source_root.parent or source_root in {Path.cwd().resolve(), Path("/")}:
        raise RuntimeError("refusing broad source retirement target")

    def verify(details: list[dict[str, Any]], root: Path) -> list[Path]:
        paths: list[Path] = []
        for item in details:
            path = Path(str(item["path"])).resolve()
            try:
                path.relative_to(root)
            except ValueError as exc:
                raise RuntimeError(f"file outside declared dataset root: {path}") from exc
            if not path.is_file() or path.is_symlink():
                raise RuntimeError(f"missing or symlinked evidence file: {path}")
            actual = _parquet_detail(path)
            expected = {key: item.get(key) for key in ("sha256", "bytes", "rows", "schema_sha256")}
            observed = {key: actual.get(key) for key in expected}
            if expected != observed:
                raise RuntimeError(f"file changed since compaction: {path}")
            paths.append(path)
        return paths

    sources = verify(source_details, source_root)
    outputs = verify(output_details, destination_root)
    if sum(int(item["rows"]) for item in source_details) != int(payload["source_rows"]):
        raise RuntimeError("source row total does not match manifest")
    return payload, sources, outputs


def retire_source(manifest_path: Path, *, apply: bool = False) -> dict[str, Any]:
    """Dry-run or precisely retire a validated compacted source tree."""
    payload, sources, _outputs = _validated_retirement(manifest_path)
    result = {
        "status": "ready_to_retire" if not apply else "retired",
        "manifest": str(manifest_path),
        "source": payload["source"],
        "files": len(sources),
        "bytes": sum(path.stat().st_size for path in sources),
        "paths": [str(path) for path in sources],
    }
    if not apply:
        return result
    empty_dirs = {
        directory
        for path in sources
        for directory in (path.parent, *path.parents)
        if directory == Path(payload["source"]).resolve()
        or Path(payload["source"]).resolve() in directory.parents
    }
    for path in sources:
        path.unlink()
    source_root = Path(payload["source"]).resolve()
    for directory in sorted(empty_dirs, key=lambda item: len(item.parts), reverse=True):
        if directory == Path("/") or not directory.exists():
            continue
        try:
            directory.rmdir()
        except OSError:
            break
    payload["retirement_status"] = "RETIRED"
    payload["retired_at"] = datetime.now(UTC).isoformat()
    payload["retired_files"] = result["files"]
    payload["retired_bytes"] = result["bytes"]
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def verify_retired(manifest_path: Path) -> dict[str, Any]:
    """Verify a retired tombstone has no source files and intact outputs."""
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("retirement_status") != "RETIRED":
        raise RuntimeError("manifest is not marked RETIRED")
    source_paths = [Path(str(item["path"])) for item in payload.get("source_file_details", [])]
    if any(path.exists() for path in source_paths):
        raise RuntimeError("retired source file still exists")
    destination = Path(payload["destination"]).resolve()
    output_details = payload.get("output_file_details") or []
    if not output_details:
        raise RuntimeError("retired manifest lacks output evidence")
    for item in output_details:
        path = Path(str(item["path"])).resolve()
        try:
            path.relative_to(destination)
        except ValueError as exc:
            raise RuntimeError(f"output outside declared destination: {path}") from exc
        if not path.is_file() or _parquet_detail(path)["sha256"] != item["sha256"]:
            raise RuntimeError(f"retained output changed or is missing: {path}")
    return {
        "status": "retired_verified",
        "manifest": str(manifest_path),
        "source_files_absent": len(source_paths),
        "output_files_verified": len(output_details),
    }


def refresh_compaction_manifest(manifest_path: Path) -> dict[str, Any]:
    """Backfill per-file evidence into an older source-preserving manifest."""
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    source = Path(payload["source"])
    destination = Path(payload["destination"])
    sources = sorted(path for path in source.rglob("*.parquet") if path.is_file())
    outputs = sorted(path for path in destination.rglob("*.parquet") if path.is_file())
    if len(sources) != int(payload["source_files"]) or len(outputs) != int(payload["output_files"]):
        raise RuntimeError("manifest file counts no longer match current source/output")
    if sum(_parquet_detail(path)["rows"] for path in sources) != int(payload["source_rows"]):
        raise RuntimeError("manifest source row count no longer matches current source")
    payload["source_file_details"] = [_parquet_detail(path) for path in sources]
    payload["output_file_details"] = [_parquet_detail(path) for path in outputs]
    payload["retirement_status"] = "SOURCE_PRESERVED"
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    inventory = sub.add_parser("inventory")
    inventory.add_argument("--root", default="data")
    inventory.add_argument("--output", default=None)
    inventory.add_argument("--top-level-limit", type=int, default=50)
    compact = sub.add_parser("compact")
    compact.add_argument("--source", required=True)
    compact.add_argument("--destination", required=True)
    compact.add_argument("--partition-by", default="symbol")
    compact.add_argument("--deduplicate-exact-rows", action="store_true")
    compact.add_argument("--deduplicate-keys", default="",
                         help="comma-separated event identity columns")
    compact.add_argument("--latest-by", default=None,
                         help="observation column used to keep newest row per key")
    compact.add_argument("--apply", action="store_true",
                         help="write the new dataset; without this flag only print the plan")
    retire = sub.add_parser("retire", help="retire only the exact validated source files in a manifest")
    retire.add_argument("--manifest", required=True)
    retire.add_argument("--apply", action="store_true",
                        help="delete the exact source files after all validations pass")
    refresh = sub.add_parser("refresh", help="add per-file evidence to an older compaction manifest")
    refresh.add_argument("--manifest", required=True)
    verify = sub.add_parser("verify-retired", help="verify a retired manifest tombstone and its outputs")
    verify.add_argument("--manifest", required=True)
    args = parser.parse_args()
    if args.command == "inventory":
        result = _file_inventory(Path(args.root), top_level_limit=args.top_level_limit)
        payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            Path(args.output).write_text(payload, encoding="utf-8")
        else:
            print(payload, end="")
        return 0
    if args.command == "retire":
        print(json.dumps(retire_source(Path(args.manifest), apply=args.apply), ensure_ascii=False, indent=2))
        return 0
    if args.command == "refresh":
        print(json.dumps(refresh_compaction_manifest(Path(args.manifest)), ensure_ascii=False, indent=2))
        return 0
    if args.command == "verify-retired":
        print(json.dumps(verify_retired(Path(args.manifest)), ensure_ascii=False, indent=2))
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
        deduplicate_keys=tuple(item for item in args.deduplicate_keys.split(",") if item),
        latest_by=args.latest_by,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
