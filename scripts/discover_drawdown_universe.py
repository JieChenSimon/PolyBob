"""Discover a frozen, data-driven deep-drawdown research universe.

The discovery pass is deliberately separate from execution.  It scans the
local daily-bar lake in one DuckDB query, selects only on a frozen training
window, and records every excluded reason.  A name with no 50% drawdown is not
bad or missing; it is simply inapplicable to this particular candidate family.
The output is a manifest for a later replay, never a promotion decision.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb


def _domain(symbol: str) -> str:
    if symbol.isdigit():
        return "A_SHARE"
    if symbol.endswith("-USDT"):
        return "CRYPTO"
    return "US_EQUITY"


def discover(*, source: Path, selection_end: str | None, min_rows: int,
             drawdown_floor: float, limit_per_domain: int,
             seed_symbols: tuple[str, ...] = ()) -> dict:
    files = str(source / "**" / "*.parquet")
    con = duckdb.connect()
    try:
        bounds = con.execute(
            """
            SELECT min(CAST(event_date AS DATE)), max(CAST(event_date AS DATE))
            FROM read_parquet(?, hive_partitioning=true, union_by_name=true)
            WHERE close IS NOT NULL AND close > 0
            """,
            [files],
        ).fetchone()
        start, end = bounds
        if start is None or end is None:
            raise RuntimeError("daily-bar lake has no positive close rows")
        if selection_end is None:
            span = (end - start).days
            selection_date = start + timedelta(days=max(1, int(span * 0.70)))
        else:
            selection_date = selection_end
        rows = con.execute(
            """
            WITH dedup AS (
                SELECT CAST(symbol AS VARCHAR) AS symbol,
                       CAST(event_date AS DATE) AS event_date,
                       CAST(close AS DOUBLE) AS close,
                       CAST(volume AS DOUBLE) AS volume,
                       ROW_NUMBER() OVER (
                           PARTITION BY CAST(symbol AS VARCHAR), CAST(event_date AS DATE)
                           ORDER BY fetched_at DESC NULLS LAST
                       ) AS rn
                FROM read_parquet(?, hive_partitioning=true, union_by_name=true)
                WHERE close IS NOT NULL AND close > 0
                  AND CAST(event_date AS DATE) <= CAST(? AS DATE)
            ), prior AS (
                SELECT *, MAX(close) OVER (
                    PARTITION BY symbol ORDER BY event_date
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                ) AS prior_peak
                FROM dedup WHERE rn = 1
            ), marked AS (
                SELECT *, CASE WHEN prior_peak IS NULL THEN NULL
                                ELSE 1.0 - close / prior_peak END AS drawdown
                FROM prior
            )
            SELECT symbol, COUNT(*) AS rows,
                   MIN(event_date) AS start, MAX(event_date) AS end,
                   MAX(drawdown) AS max_drawdown,
                   COUNT(*) FILTER (WHERE drawdown >= 0.50) AS deep_drawdown_rows,
                   AVG(volume) FILTER (WHERE volume IS NOT NULL AND volume > 0) AS avg_volume
            FROM marked
            GROUP BY symbol
            """,
            [files, str(selection_date)],
        ).fetchall()
    finally:
        con.close()

    candidates: list[dict] = []
    records_by_symbol: dict[str, dict] = {}
    excluded: list[dict] = []
    for symbol, count, first, last, max_dd, deep_rows, avg_volume in rows:
        symbol = str(symbol)
        domain = _domain(symbol)
        record = {
            "symbol": symbol,
            "domain": domain,
            "rows": int(count),
            "start": str(first),
            "end": str(last),
            "max_drawdown": float(max_dd or 0.0),
            "deep_drawdown_rows": int(deep_rows or 0),
            "avg_volume": float(avg_volume or 0.0),
        }
        records_by_symbol[symbol] = record
        reason = None
        if count < min_rows:
            reason = "insufficient_training_rows"
        elif float(max_dd or 0.0) < drawdown_floor:
            reason = "no_training_drawdown_candidate"
        elif not avg_volume or float(avg_volume) <= 0:
            reason = "missing_or_zero_volume"
        if reason:
            excluded.append({**record, "excluded_reason": reason})
        else:
            candidates.append(record)

    selected: list[dict] = []
    for domain in ("A_SHARE", "US_EQUITY", "CRYPTO"):
        pool = sorted(
            (item for item in candidates if item["domain"] == domain),
            key=lambda item: (item["deep_drawdown_rows"], item["max_drawdown"], item["rows"]),
            reverse=True,
        )
        selected.extend(pool[:limit_per_domain])
    selected_symbols = {item["symbol"] for item in selected}
    for seed in seed_symbols:
        record = records_by_symbol.get(str(seed).strip())
        if record is not None and record["symbol"] not in selected_symbols:
            selected.append({**record, "selection_reason": "explicit_user_seed"})
            selected_symbols.add(record["symbol"])
    return {
        "schema_version": "drawdown-universe-discovery-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "real_data_only": True,
        "selection_end": str(selection_date),
        "selection_rule": {
            "min_training_rows": min_rows,
            "drawdown_floor": drawdown_floor,
            "limit_per_domain": limit_per_domain,
            "seed_symbols": list(seed_symbols),
            "uses_oos": False,
        },
        "candidate_symbols": [item["symbol"] for item in selected],
        "selected": selected,
        "selected_count": len(selected),
        "scanned_count": len(rows),
        "excluded_count": len(excluded),
        "excluded_reason_counts": {
            reason: sum(item["excluded_reason"] == reason for item in excluded)
            for reason in sorted({item["excluded_reason"] for item in excluded})
        },
        "excluded_sample": excluded[:200],
        "promotion": "BLOCKED",
        "limitations": [
            "local daily bars are not complete survivorship-controlled history",
            "fundamental and executable-quote gates are evaluated downstream",
            "selection is a training-universe screen, not a trading signal",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("data/store/daily_bars"))
    parser.add_argument("--selection-end")
    parser.add_argument("--min-rows", type=int, default=250)
    parser.add_argument("--drawdown-floor", type=float, default=0.40)
    parser.add_argument("--limit-per-domain", type=int, default=50)
    parser.add_argument("--seed-symbols", default="SNDK,MU,WDC,MRVL")
    parser.add_argument("--output", type=Path, default=Path("data/drawdown_universe_discovery.json"))
    args = parser.parse_args()
    report = discover(
        source=args.source,
        selection_end=args.selection_end,
        min_rows=args.min_rows,
        drawdown_floor=args.drawdown_floor,
        limit_per_domain=args.limit_per_domain,
        seed_symbols=tuple(item.strip() for item in args.seed_symbols.split(",") if item.strip()),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "selected_count": report["selected_count"],
        "scanned_count": report["scanned_count"],
        "selection_end": report["selection_end"],
        "output": str(args.output),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
