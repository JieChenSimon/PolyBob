"""Backfill only provider-declared price semantics in the local daily-bar lake.

This is a metadata correction, not a price correction.  It creates a new
observation vintage because the original rows did not declare the basis.  No
value is inferred from the price series; unknown providers remain unknown.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

from libs.data import store


def _domain(symbol: str) -> str:
    if symbol.isdigit():
        return "a_share"
    if symbol.endswith("-USDT"):
        return "crypto"
    return "us_equity"


def _declared_basis(source: str | None) -> str | None:
    if source in {"tencent", "tencent_migrated"}:
        return "forward_adjusted"
    if source in {"okx", "okx_migrated"}:
        return "unadjusted"
    if source in {"yahoo", "yahoo_migrated"}:
        return "provider_quote_adjustment_unknown"
    return None


def _missing(value: object) -> bool:
    return value is None or value == "" or (isinstance(value, float) and value != value)


def backfill(*, domains: set[str], dry_run: bool = False) -> dict:
    now = datetime.now(UTC)
    selected = [symbol for symbol in store.symbols(store.DAILY_BARS)
                if _domain(symbol) in domains]
    changed_symbols = changed_rows = unknown_rows = 0
    by_domain: dict[str, dict[str, int]] = {}
    for symbol in selected:
        frame = store.read(store.DAILY_BARS, symbol, as_of=now)
        if frame.empty:
            continue
        changed = 0
        rows = frame.to_dict("records")
        for row in rows:
            if not _missing(row.get("price_basis")):
                continue
            basis = _declared_basis(str(row.get("source")) if row.get("source") else None)
            if basis is None:
                unknown_rows += 1
                continue
            row["price_basis"] = basis
            changed += 1
        if changed and not dry_run:
            store.write(store.DAILY_BARS, symbol, rows,
                        # This is deliberately a new observation vintage. The
                        # old migration may have the same file mtime as its
                        # payload, and content-addressed deduplication would
                        # leave the reader free to select the undeclared row.
                        fetched_at=now, deduplicate_payload=False)
        if changed:
            changed_symbols += 1
            changed_rows += changed
            bucket = by_domain.setdefault(_domain(symbol), {"symbols": 0, "rows": 0})
            bucket["symbols"] += 1
            bucket["rows"] += changed
    return {
        "generated_at": now.isoformat(),
        "domains": sorted(domains),
        "dry_run": dry_run,
        "selected_symbols": len(selected),
        "changed_symbols": changed_symbols,
        "changed_rows": changed_rows,
        "unknown_rows": unknown_rows,
        "by_domain": by_domain,
        "status": "planned" if dry_run else "completed",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", action="append", choices=("a_share", "crypto", "us_equity"),
                        default=["a_share", "crypto"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(backfill(domains=set(args.domain), dry_run=args.dry_run),
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
