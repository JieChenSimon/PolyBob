"""Fail-closed audit of data evidence required for strategy promotion.

This command does not acquire or delete data. It inspects declared contracts,
coverage, and explicitly named local evidence artifacts. Missing evidence is
reported as UNKNOWN rather than treated as a pass.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from libs.data import store


def _matching_files(root: Path, terms: tuple[str, ...]) -> list[str]:
    if not root.exists():
        return []
    matches: list[str] = []
    for path in root.rglob("*"):
        if path.is_file() and any(term in path.name.lower() for term in terms):
            matches.append(str(path))
    return sorted(matches)


def audit(*, data_root: Path = Path("data")) -> dict[str, Any]:
    contracts = store.dataset_contracts()
    daily = store.coverage(store.DAILY_BARS)
    fundamentals = store.coverage(store.FUNDAMENTALS)
    quote_files = _matching_files(data_root, ("quote", "depth", "orderbook", "bbo"))
    survivorship_files = _matching_files(data_root, ("delist", "listing", "survivorship"))

    strict_pit_ready = bool(
        contracts["daily_bars"].get("strict_historical_pit")
        and contracts["fundamentals"].get("strict_historical_pit")
    )
    # A discovered/current universe is not historical membership evidence. A
    # dedicated file with explicit effective/observed timestamps is required.
    survivorship_ready = False
    execution_ready = bool(quote_files)
    gates = {
        "strict_historical_pit": {
            "status": "READY" if strict_pit_ready else "UNKNOWN",
            "reason": None if strict_pit_ready else "declared_daily_or_fundamental_contract_is_not_strict_historical_pit",
        },
        "survivorship_control": {
            "status": "READY" if survivorship_ready else "UNKNOWN",
            "reason": None if survivorship_ready else "no_dedicated_point_in_time_listing_delisting_contract",
        },
        "historical_executable_quotes": {
            "status": "READY" if execution_ready else "UNKNOWN",
            "reason": None if execution_ready else "no_local_historical_quote_depth_artifact",
        },
    }
    overall = "READY" if all(item["status"] == "READY" for item in gates.values()) else "BLOCKED"
    return {
        "schema_version": "evidence-readiness-audit-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "read_only": True,
        "promotion": overall,
        "gates": gates,
        "contracts": {
            "daily_bars": contracts["daily_bars"],
            "fundamentals": contracts["fundamentals"],
        },
        "coverage": {"daily_bars": daily, "fundamentals": fundamentals},
        "artifacts": {
            "historical_quote_like_files": quote_files,
            "survivorship_like_files": survivorship_files,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, default=Path("data/evidence_readiness_audit.json"))
    args = parser.parse_args()
    result = audit(data_root=args.data_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"promotion": result["promotion"], "gates": result["gates"]}, ensure_ascii=False, indent=2))
    print(f"写入 {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
