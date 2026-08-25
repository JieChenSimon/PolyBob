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


def _manifest_entries(data_root: Path) -> list[dict[str, Any]]:
    manifest = data_root / "datasets" / "manifest.jsonl"
    if not manifest.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            entries.append(item)
    return entries


def _execution_replay_files(data_root: Path) -> list[dict[str, Any]]:
    """Read explicit real-data replay summaries, never infer from filenames alone."""
    results: list[dict[str, Any]] = []
    for path in sorted(data_root.glob("*okx_l2_imbalance_replay*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            metrics = payload.get("metrics") or {}
            evidence = metrics.get("execution_evidence") or {}
            results.append({
                "path": str(path),
                "real_data_only": payload.get("real_data_only"),
                "strategy": payload.get("strategy"),
                "instrument": payload.get("instrument"),
                "run_id": payload.get("run_id"),
                "rows_used": payload.get("rows_used"),
                "linked_observations": payload.get("linked_observations"),
                "status": payload.get("status"),
                "total_return": metrics.get("total_return"),
                "trade_count": metrics.get("trade_count"),
                "trade_quote_observation_link_count": evidence.get(
                    "trade_quote_observation_link_count"
                ),
                "synthetic_quote_trade_count": evidence.get("synthetic_quote_trade_count"),
            })
    return results


def audit(*, data_root: Path = Path("data")) -> dict[str, Any]:
    contracts = store.dataset_contracts()
    daily = store.coverage(store.DAILY_BARS)
    fundamentals = store.coverage(store.FUNDAMENTALS)
    quote_files = _matching_files(data_root, ("quote", "depth", "orderbook", "bbo"))
    survivorship_files = _matching_files(data_root, ("delist", "listing", "survivorship"))
    manifest_entries = _manifest_entries(data_root)
    live_quote_entries = [item for item in manifest_entries if item.get("dataset") == "okx_orderbook"]
    historical_quote_entries = [item for item in manifest_entries if item.get("dataset") == "historical_orderbook"]
    sampled_historical_quote_entries = [
        item for item in manifest_entries
        if item.get("dataset") == "okx_historical_orderbook_sampled_1s"
    ]
    execution_replays = _execution_replay_files(data_root)
    linked_real_replay = [
        item for item in execution_replays
        if item.get("real_data_only") is True
        and int(item.get("linked_observations", 0) or 0) > 0
        and int(item.get("trade_quote_observation_link_count", 0) or 0) > 0
    ]

    strict_pit_ready = bool(
        contracts["daily_bars"].get("strict_historical_pit")
        and contracts["fundamentals"].get("strict_historical_pit")
    )
    # A discovered/current universe is not historical membership evidence. A
    # dedicated file with explicit effective/observed timestamps is required.
    survivorship_ready = False
    execution_ready = bool(historical_quote_entries)
    execution_reason = None
    if not execution_ready:
        execution_reason = (
            "sampled_historical_orderbook_has_partial_fill_linkage_but_insufficient_coverage"
            if linked_real_replay else
            "sampled_historical_orderbook_present_but_fill_linkage_missing"
            if sampled_historical_quote_entries else
            "historical_quote_dataset_missing;_live_snapshots_present_but_not_historical"
            if live_quote_entries
            else "no_local_historical_quote_depth_artifact"
        )
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
            "reason": execution_reason,
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
            "live_quote_observation_entries": live_quote_entries,
            "historical_quote_entries": historical_quote_entries,
            "sampled_historical_quote_entries": sampled_historical_quote_entries,
            "real_execution_replay_summaries": execution_replays,
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
