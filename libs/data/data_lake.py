"""Local content-addressed data lake for real provider observations.

The bitemporal ``libs.data.store`` remains the canonical query layer for daily
datasets. This module complements it for arbitrary timestamps (1m/5m bars,
order-book observations, settled markets) and for immutable raw provider
responses. Every artifact is content-addressed and described by a manifest, so
re-fetches are deduplicated while provider restatements remain distinct.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(os.environ.get("POLYBOB_DATASETS", "data/datasets"))
RAW_ROOT = ROOT / "raw"
PART_ROOT = ROOT / "parts"
MANIFEST = ROOT / "manifest.jsonl"
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
_MANIFEST_CACHE_KEY: tuple[str, int] | None = None
_MANIFEST_CACHE: list[dict[str, Any]] = []
_RAW_DIGEST_CACHE_KEY: tuple[str, int] | None = None
_RAW_DIGESTS: set[str] = set()


def _safe(value: Any) -> str:
    return _SAFE.sub("_", str(value)).strip("_") or "unknown"


def _utc(value: dt.datetime | None = None) -> str:
    value = value or dt.datetime.now(dt.UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC).isoformat()


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _append_manifest(entry: Mapping[str, Any]) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(entry), sort_keys=True, ensure_ascii=False) + "\n")


def record_raw(
    dataset: str,
    payload: bytes,
    *,
    source: str,
    request: str | None = None,
    observed_at: dt.datetime | None = None,
) -> dict[str, Any]:
    """Persist one immutable raw provider response and its provenance."""
    digest = _digest(payload)
    target_dir = RAW_ROOT / _safe(dataset) / _safe(source)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{digest}.bin"
    if not target.exists():
        fd, raw_pending = tempfile.mkstemp(dir=target_dir, prefix=".pending-")
        os.close(fd)
        pending = Path(raw_pending)
        try:
            pending.write_bytes(payload)
            pending.replace(target)
        finally:
            pending.unlink(missing_ok=True)
    entry = {
        "kind": "raw",
        "dataset": dataset,
        "source": source,
        "request": request,
        "sha256": digest,
        "path": str(target),
        "bytes": len(payload),
        "observed_at": _utc(observed_at),
    }
    # A duplicate response is still useful in the cache but does not create a
    # second manifest row; the content hash is the idempotency key.
    global _RAW_DIGEST_CACHE_KEY, _RAW_DIGESTS
    manifest_entries = read_manifest()
    stat = MANIFEST.stat() if MANIFEST.exists() else None
    manifest_key = (str(MANIFEST), stat.st_mtime_ns if stat else -1)
    if manifest_key != _RAW_DIGEST_CACHE_KEY:
        _RAW_DIGESTS = {
            str(item.get("sha256")) for item in manifest_entries
            if item.get("kind") == "raw" and item.get("sha256")
        }
        _RAW_DIGEST_CACHE_KEY = manifest_key
    if digest not in _RAW_DIGESTS:
        _append_manifest(entry)
        _RAW_DIGESTS.add(digest)
    return entry


def write_records(
    dataset: str,
    records: Iterable[Mapping[str, Any]],
    *,
    source: str,
    observed_at: dt.datetime | None = None,
    partition_by: tuple[str, ...] = ("symbol",),
) -> dict[str, Any]:
    """Write normalized records to a deduplicated Parquet dataset.

    Records should include ``event_at`` (market time) and may include
    ``effective_at``/``observed_at`` fields. The lake does not invent missing
    event time; a malformed record is rejected before a file is written.
    """
    rows = [dict(row) for row in records]
    if not rows:
        return {"dataset": dataset, "rows": 0, "status": "empty"}
    observed = _utc(observed_at)
    for row in rows:
        if not row.get("event_at"):
            raise ValueError(f"{dataset}: every record needs event_at")
        row.setdefault("observed_at", observed)

    # Partition independently. The digest excludes observed_at so repeating the
    # same normalized payload at a later observation time is idempotent.
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for row in rows:
        key = tuple(str(row.get(part, "unknown")) for part in partition_by)
        grouped.setdefault(key, []).append(row)
    written: list[dict[str, Any]] = []
    for key, group in grouped.items():
        canonical = []
        for row in group:
            value = dict(row)
            value.pop("observed_at", None)
            canonical.append(value)
        canonical.sort(key=lambda value: json.dumps(value, sort_keys=True,
                                                    ensure_ascii=False, default=str,
                                                    separators=(",", ":")))
        digest = _digest(json.dumps(canonical, ensure_ascii=False, sort_keys=True,
                                    default=str, separators=(",", ":")).encode())
        parts = PART_ROOT / _safe(dataset)
        for part, value in zip(partition_by, key):
            parts /= f"{_safe(part)}={_safe(value)}"
        parts.mkdir(parents=True, exist_ok=True)
        target = parts / f"part-{digest}.parquet"
        if not target.exists():
            table = pa.Table.from_pylist(group)
            fd, raw_pending = tempfile.mkstemp(dir=parts, prefix=".pending-", suffix=".parquet")
            os.close(fd)
            pending = Path(raw_pending)
            try:
                pq.write_table(table, pending, compression="zstd")
                pending.replace(target)
            finally:
                pending.unlink(missing_ok=True)
            _append_manifest({
                "kind": "normalized", "dataset": dataset, "source": source,
                "sha256": digest, "path": str(target), "rows": len(group),
                "event_start": min(str(row["event_at"]) for row in group),
                "event_end": max(str(row["event_at"]) for row in group),
                "observed_at": observed, "partition_by": list(partition_by),
            })
        written.append({"path": str(target), "sha256": digest, "rows": len(group)})
    return {"dataset": dataset, "rows": len(rows), "parts": written,
            "path": written[0]["path"], "sha256": written[0]["sha256"],
            "status": "written" if written else "unknown"}


def read_manifest() -> list[dict[str, Any]]:
    global _MANIFEST_CACHE_KEY, _MANIFEST_CACHE
    if not MANIFEST.exists():
        return []
    stat = MANIFEST.stat()
    key = (str(MANIFEST), stat.st_mtime_ns)
    if key == _MANIFEST_CACHE_KEY:
        return _MANIFEST_CACHE
    entries: list[dict[str, Any]] = []
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                entries.append(value)
        except ValueError:
            continue
    _MANIFEST_CACHE_KEY = key
    _MANIFEST_CACHE = entries
    return entries


def inventory() -> dict[str, dict[str, Any]]:
    """Summarize locally persisted raw and normalized datasets."""
    out: dict[str, dict[str, Any]] = {}
    for entry in read_manifest():
        item = out.setdefault(entry.get("dataset", "unknown"), {"raw": 0, "parts": 0, "rows": 0})
        if entry.get("kind") == "raw":
            item["raw"] += 1
        else:
            item["parts"] += 1
            item["rows"] += int(entry.get("rows") or 0)
    return out


__all__ = ["MANIFEST", "PART_ROOT", "RAW_ROOT", "ROOT", "inventory", "read_manifest", "record_raw", "write_records"]
