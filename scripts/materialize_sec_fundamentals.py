"""Materialize real SEC XBRL fundamentals for the quality-gated watchlist."""

from __future__ import annotations

import json
import sys
import argparse
from pathlib import Path

from libs.data.sec_fundamentals import SecFundamentalsUnavailable, materialize


def _symbols_from_args(argv: list[str]) -> list[str]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbols", nargs="*")
    parser.add_argument("--symbols-file", type=Path,
                        help="discovery JSON list or manifest with candidate_symbols")
    parser.add_argument("--limit", type=int, default=0,
                        help="maximum symbols to materialize, 0 means all")
    parser.add_argument("--us-only", action="store_true",
                        help="exclude A-share numeric codes and -USDT pairs")
    args = parser.parse_args(argv)
    if args.symbols_file:
        payload = json.loads(args.symbols_file.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            if "candidates" in payload:
                payload = [
                    row.get("symbol") for row in payload.get("candidates", [])
                    if row.get("status") == "READY_FOR_RESEARCH"
                ]
            else:
                payload = payload.get("candidate_symbols", [])
        symbols = [str(item).upper() for item in payload]
    else:
        symbols = [s.upper() for s in (args.symbols or [
        "SNDK", "MU", "WDC", "MRVL", "AMD", "NVDA", "TSLA", "ADBE", "INTC", "DIS", "F", "UPS",
        ])]
    if args.us_only:
        symbols = [s for s in symbols if not s.isdigit() and not s.endswith("-USDT")]
    return symbols[:args.limit] if args.limit > 0 else symbols


def main(argv: list[str]) -> int:
    symbols = _symbols_from_args(argv)
    results = []
    for symbol in symbols:
        try:
            results.append(materialize(symbol))
        except SecFundamentalsUnavailable as exc:
            results.append({"symbol": symbol, "status": "UNKNOWN", "reason": str(exc)})
    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0 if all(item.get("status") == "available" for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main(__import__("sys").argv[1:]))
