"""Download and register real OKX historical L2 order-book archives.

The official OKX historical-data service returns gzip tar archives containing
newline-delimited snapshot/update records.  This command stores the immutable
archive content-addressed and records the request/date/provenance in the local
manifest.  It intentionally does not label a download as executable evidence
until a later parser reconstructs the book and links sampled observations to
fills.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from libs.data.data_lake import MANIFEST, ROOT, read_manifest

LINK_API = "https://www.okx.com/priapi/v5/broker/public/trade-data/download-link"
MODULE_BY_DEPTH = {400: "4", 5000: "5"}


def _utc_ms(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1000)


def download_links(symbols: list[str], *, inst_type: str, begin: str, end: str,
                   depth: int) -> list[dict[str, Any]]:
    if depth not in MODULE_BY_DEPTH:
        raise ValueError("depth must be 400 or 5000")
    payload = {
        "module": MODULE_BY_DEPTH[depth],
        "instType": inst_type,
        "instQueryParam": {
            "instIdList": symbols if inst_type == "SPOT" else None,
            "instFamilyList": symbols if inst_type != "SPOT" else None,
        },
        "dateQuery": {
            "dateAggrType": "daily",
            "begin": str(_utc_ms(begin)),
            "end": str(_utc_ms(end)),
        },
    }
    request = urllib.request.Request(
        LINK_API,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "PolyBob real-data research"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        result = json.load(response)
    if str(result.get("code")) != "0":
        raise RuntimeError(f"OKX historical link request failed: {result}")
    links: list[dict[str, Any]] = []
    for detail in (result.get("data") or {}).get("details", []):
        for item in detail.get("groupDetails", []):
            links.append({
                "url": str(item["url"]),
                "filename": str(item["filename"]),
                "size_mb": float(item.get("sizeMB") or 0),
                "date_ts": str(item.get("dateTs") or ""),
                "inst_id": detail.get("instId") or detail.get("instFamily"),
            })
    return links


def _download(url: str, target: Path, *, max_bytes: int) -> dict[str, Any]:
    target.parent.mkdir(parents=True, exist_ok=True)
    pending = target.with_name(f".{target.name}.pending")
    digest = hashlib.sha256()
    size = 0
    request = urllib.request.Request(url, headers={"User-Agent": "PolyBob real-data research"})
    try:
        with urllib.request.urlopen(request, timeout=180) as response, pending.open("wb") as handle:
            expected = int(response.headers.get("Content-Length") or 0)
            if expected > max_bytes:
                raise ValueError(f"archive is {expected} bytes, above max_bytes={max_bytes}")
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError(f"archive exceeded max_bytes={max_bytes}")
                digest.update(chunk)
                handle.write(chunk)
        pending.replace(target)
    finally:
        pending.unlink(missing_ok=True)
    return {"path": str(target), "sha256": digest.hexdigest(), "bytes": size}


def register_archive(link: dict[str, Any], downloaded: dict[str, Any], *, begin: str, end: str,
                     depth: int, source_url: str) -> None:
    entry = {
        "kind": "raw",
        "dataset": "okx_historical_orderbook_l2_raw",
        "source": "www.okx.com_historical_data",
        "request": source_url,
        "sha256": downloaded["sha256"],
        "path": downloaded["path"],
        "bytes": downloaded["bytes"],
        "event_start": begin,
        "event_end": end,
        "instrument": link.get("inst_id"),
        "depth": depth,
        "history_scope": "historical_orderbook_raw_archive",
        "registered_at": datetime.now(UTC).isoformat(),
    }
    existing = {str(item.get("sha256")) for item in read_manifest() if item.get("kind") == "raw"}
    if entry["sha256"] not in existing:
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        with MANIFEST.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def import_archives(symbols: list[str], *, inst_type: str, begin: str, end: str,
                    depth: int, output_dir: Path, max_bytes: int,
                    dry_run: bool = False) -> dict[str, Any]:
    links = download_links(symbols, inst_type=inst_type, begin=begin, end=end, depth=depth)
    archives = []
    for link in links:
        target = output_dir / link["filename"]
        item = {**link, "target": str(target), "status": "planned"}
        if not dry_run:
            downloaded = _download(link["url"], target, max_bytes=max_bytes)
            register_archive(link, downloaded, begin=begin, end=end, depth=depth,
                             source_url=link["url"])
            item.update(downloaded, status="downloaded", history_scope="historical_orderbook_raw_archive")
        archives.append(item)
    return {
        "schema_version": "okx-historical-l2-import-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "real_data_only": True,
        "provider": "OKX official historical market data",
        "inst_type": inst_type,
        "symbols": symbols,
        "begin": begin,
        "end": end,
        "depth": depth,
        "archives": archives,
        "promotion": "BLOCKED",
        "promotion_reason": "raw_archive_requires_book_reconstruction_and_fill_linkage",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="BTC-USDT")
    parser.add_argument("--inst-type", default="SPOT", choices=("SPOT", "SWAP", "FUTURES", "OPTION"))
    parser.add_argument("--begin", required=True, help="UTC ISO date/time, inclusive")
    parser.add_argument("--end", required=True, help="UTC ISO date/time, exclusive")
    parser.add_argument("--depth", type=int, default=400, choices=(400, 5000))
    parser.add_argument("--output-dir", type=Path, default=ROOT / "raw" / "okx_historical_orderbook_l2")
    parser.add_argument("--max-bytes", type=int, default=2_000_000_000)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()
    result = import_archives(
        [item.strip() for item in args.symbols.split(",") if item.strip()],
        inst_type=args.inst_type, begin=args.begin, end=args.end, depth=args.depth,
        output_dir=args.output_dir, max_bytes=args.max_bytes, dry_run=args.dry_run,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
