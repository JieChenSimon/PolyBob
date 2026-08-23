"""Materialize normalized SEC filings from already cached quarterly archives."""

from __future__ import annotations

from libs.data.sec_insider import fetch_insider_trades


def main() -> None:
    quarters = ((2025, 3), (2025, 4), (2026, 1))
    total = 0
    for year, quarter in quarters:
        trades = fetch_insider_trades(year, quarter)
        total += len(trades)
        print(f"{year}Q{quarter}: {len(trades):,} transactions")
    print(f"materialized sec_filings: {total:,} transactions")


if __name__ == "__main__":
    main()
