"""Fetch and record the real Deribit BTC/ETH funding coverage."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from libs.data.real_sources import fetch_deribit_funding_rate_daily


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=400)
    parser.add_argument("--output", type=Path, default=Path("data/deribit_funding_coverage.json"))
    args = parser.parse_args()
    result = {}
    for symbol in ("BTC-PERPETUAL", "ETH-PERPETUAL"):
        values = fetch_deribit_funding_rate_daily(symbol, days=args.days)
        result[symbol] = {
            "rows": len(values),
            "start": min(values),
            "end": max(values),
            "source": "deribit_interest_1h_daily_sum",
        }
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "real_data_only": True,
        "endpoint": "https://www.deribit.com/api/v2/public/get_funding_rate_history",
        "requested_days": args.days,
        "symbols": result,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
