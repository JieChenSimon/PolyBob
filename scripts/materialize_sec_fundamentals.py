"""Materialize real SEC XBRL fundamentals for the quality-gated watchlist."""

from __future__ import annotations

import json
import sys

from libs.data.sec_fundamentals import SecFundamentalsUnavailable, materialize


def main(argv: list[str]) -> int:
    symbols = [s.upper() for s in (argv or ["SNDK", "MU", "WDC"])]
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
