"""Materialize normalized SEC filings from already cached quarterly archives."""

from __future__ import annotations

from libs.data.sec_insider import fetch_insider_trades


def main() -> None:
    # SEC publishes the structured archive quarterly. Keep a contiguous window
    # so the study can be rerun without a hidden recent-history selection.
    quarters = tuple(
        (year, quarter)
        for year in (2024, 2025, 2026)
        for quarter in (1, 2, 3, 4)
        if (year, quarter) <= (2026, 2)
    )
    total = 0
    for year, quarter in quarters:
        trades = fetch_insider_trades(year, quarter)
        total += len(trades)
        print(f"{year}Q{quarter}: {len(trades):,} transactions")
    print(f"materialized sec_filings: {total:,} transactions")


if __name__ == "__main__":
    main()
