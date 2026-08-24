"""Compact the BTC 5m v6 normalized lake without losing the old parts.

The collector writes small content-addressed parts while it is running. This
one-shot maintenance command creates one canonical part, archives the prior
parts and rewrites only the v6 normalized manifest entries. It is deliberately
dry-run by default because the operation changes the local dataset layout.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from libs.data import data_lake


DATASET = "btc5m_settled_windows_v6"


def _digest(rows: list[dict[str, object]]) -> str:
    canonical = []
    for row in rows:
        value = dict(row)
        value.pop("observed_at", None)
        canonical.append(value)
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True,
                         default=str, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _load_rows() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    entries = [entry for entry in data_lake.read_manifest()
               if entry.get("kind") == "normalized"
               and entry.get("dataset") == DATASET]
    rows: dict[int, dict[str, object]] = {}
    for entry in entries:
        path = Path(str(entry["path"]))
        if not path.exists():
            raise FileNotFoundError(f"manifest points to missing part: {path}")
        for row in pq.read_table(path).to_pylist():
            key = int(row["window_start"])
            previous = rows.get(key)
            if previous is None or str(row.get("observed_at", "")) > str(previous.get("observed_at", "")):
                rows[key] = row
    ordered = [rows[key] for key in sorted(rows)]
    return ordered, entries


def compact(*, apply: bool) -> None:
    rows, old_entries = _load_rows()
    part_root = data_lake.PART_ROOT / DATASET
    if not rows:
        raise RuntimeError(f"no rows found for {DATASET}")
    digest = _digest(rows)
    target_name = f"part-{digest}.parquet"
    now = dt.datetime.now(dt.UTC)
    archive = data_lake.ROOT / "archive" / f"{DATASET}-precompact-{now:%Y%m%dT%H%M%S%fZ}"
    new_entry = {
        "kind": "normalized",
        "dataset": DATASET,
        "source": "polymarket_gamma_clob_okx",
        "sha256": digest,
        "path": str(part_root / "symbol=BTC-USDT" / target_name),
        "rows": len(rows),
        "event_start": min(str(row["event_at"]) for row in rows),
        "event_end": max(str(row["event_at"]) for row in rows),
        "observed_at": max(str(row.get("observed_at", "")) for row in rows),
        "partition_by": ["symbol"],
        "maintenance": "compact_btc5m_v6",
    }
    print(json.dumps({
        "dataset": DATASET,
        "old_parts": len(old_entries),
        "old_rows": sum(int(entry.get("rows", 0) or 0) for entry in old_entries),
        "unique_rows": len(rows),
        "target": str(new_entry["path"]),
        "archive": str(archive),
        "apply": apply,
    }, ensure_ascii=False, indent=2))
    if not apply:
        return

    archive.mkdir(parents=True, exist_ok=False)
    manifest = data_lake.MANIFEST
    manifest_backup = archive / "manifest-before.jsonl"
    shutil.copy2(manifest, manifest_backup)

    parent = part_root.parent
    staging = Path(tempfile.mkdtemp(prefix=f".{DATASET}.compact-", dir=parent))
    try:
        target_dir = staging / "symbol=BTC-USDT"
        target_dir.mkdir(parents=True)
        pq.write_table(pa.Table.from_pylist(rows), target_dir / target_name, compression="zstd")

        all_entries = data_lake.read_manifest()
        kept = [entry for entry in all_entries
                if not (entry.get("kind") == "normalized" and entry.get("dataset") == DATASET)]
        manifest_tmp = manifest.with_suffix(".jsonl.compact.tmp")
        with manifest_tmp.open("w", encoding="utf-8") as handle:
            for entry in [*kept, new_entry]:
                handle.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")

        shutil.move(str(part_root), str(archive / "parts"))
        os.replace(staging, part_root)
        os.replace(manifest_tmp, manifest)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    print(f"compacted {DATASET}: {len(old_entries)} parts -> 1; archive={archive}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="apply the recoverable compaction")
    compact(apply=parser.parse_args().apply)
