"""Materialize real A-share financial indicators with an explicit non-PIT flag.

Akshare/Sina provides report-period indicators but this endpoint does not expose
the historical public announcement timestamp needed for a trading filter.  Rows
are therefore useful for descriptive analysis only and remain UNKNOWN for PIT
promotion until an announcement-date join is added.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import akshare as ak

from libs.data import store
from libs.data.data_lake import record_raw


METRICS = {
    "net_income": "归母净利润",
    "revenue": "营业总收入",
    "operating_cash_flow": "经营现金流量净额",
    "cost": "营业成本",
}


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _exchange_symbol(symbol: str) -> str:
    clean = symbol.upper().strip()
    if clean.startswith(("SH", "SZ", "BJ")):
        return clean
    if clean.startswith(("6", "68", "9")):
        return f"SH{clean}"
    return f"SZ{clean}"


def transform(symbol: str, frame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if frame is None or frame.empty:
        return rows
    date_columns = [str(column)[:8] for column in frame.columns[2:]
                    if str(column)[:8].isdigit() and len(str(column)[:8]) == 8]
    for date in sorted(set(date_columns)):
        values: dict[str, float | None] = {}
        for key, metric in METRICS.items():
            matches = frame[frame["指标"].astype(str) == metric]
            values[key] = _number(matches.iloc[0][date]) if not matches.empty else None
        revenue, cost = values["revenue"], values["cost"]
        if values["revenue"] is None and values["net_income"] is None:
            continue
        rows.append({
            "symbol": symbol,
            store.EVENT_DATE: f"{date[:4]}-{date[4:6]}-{date[6:8]}",
            "period_end": f"{date[:4]}-{date[4:6]}-{date[6:8]}",
            "announcement_at": None,
            "filing_id": f"akshare:{symbol}:{date}",
            "source": "akshare_sina_financial_abstract",
            "quality_flags": {
                "announcement_at": "missing",
                "strict_historical_pit": False,
                "period_end_only": True,
            },
            "revenue": revenue,
            "net_income": values["net_income"],
            "operating_cash_flow": values["operating_cash_flow"],
            "gross_profit": (revenue - cost) if revenue is not None and cost is not None else None,
            "cash": None,
            "total_debt": None,
        })
    return rows


def materialize(symbol: str) -> dict[str, Any]:
    clean = symbol.upper().strip()
    frame = ak.stock_financial_abstract(clean)
    raw = frame.to_json(orient="split", force_ascii=False).encode()
    request = f"https://vip.stock.finance.sina.com.cn/corp/go.php/vFD_FinanceSummary/stockid/{clean}.phtml"
    digest = hashlib.sha256(raw).hexdigest()
    record_raw("a_share_fundamentals_raw", raw, source="akshare/sina", request=request)
    rows = transform(clean, frame)
    written = store.write(store.FUNDAMENTALS, clean, rows, deduplicate_payload=True) if rows else 0
    return {
        "symbol": clean,
        "rows": len(rows),
        "written": written,
        "raw_sha256": digest,
        "announcement_at": "missing",
        "strict_historical_pit": False,
        "status": "available" if rows else "empty",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbols", nargs="*")
    parser.add_argument("--symbols-file", type=Path,
                        help="JSON list or manifest with candidate_symbols")
    parser.add_argument("--all-local", action="store_true",
                        help="materialize every numeric symbol in the local daily-bar store")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--output", type=Path,
                        default=Path("data/a_share_fundamentals_materialization.json"))
    args = parser.parse_args()
    if args.symbols_file:
        payload = json.loads(args.symbols_file.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload = payload.get("candidate_symbols", [])
        symbols = [str(item).upper() for item in payload]
    elif args.all_local:
        symbols = [symbol for symbol in store.symbols(store.DAILY_BARS) if symbol.isdigit()]
    else:
        symbols = args.symbols or ["600519", "000001", "300750", "601318", "000858"]
    symbols = symbols[:args.limit] if args.limit > 0 else symbols
    results = []
    for symbol in symbols:
        try:
            results.append(materialize(symbol))
        except Exception as exc:  # provider-specific failures remain visible per symbol
            results.append({"symbol": symbol, "status": "UNKNOWN", "reason": str(exc)})
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "requested": len(symbols),
        "available": sum(item.get("status") == "available" for item in results),
        "unknown": sum(item.get("status") == "UNKNOWN" for item in results),
        "materialized_locally": sorted(
            symbol for symbol in store.symbols(store.FUNDAMENTALS) if symbol.isdigit()
        ),
        "provider_failure_does_not_delete_local_rows": True,
        "results": results,
        "strict_historical_pit": False,
        "promotion": "BLOCKED",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["unknown"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
