"""Run a bounded, auditable equity-universe refresh.

The pipeline discovers symbols from real market rosters, optionally warms a
small UNKNOWN batch using the existing rate-limited fetcher, then rebuilds the
manifest.  It deliberately does not promote a symbol or claim profitability.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from libs.data.universe_discovery import discover_equity_candidates
from scripts.warm_equity_universe import warm_batch


def refresh_universe(
    *,
    domains: tuple[str, ...] = ("us_equity", "a_share"),
    output: str | Path = "data/discovered_equity_universe.json",
    warm_symbols_per_domain: int = 0,
    warm_interval_seconds: float = 1.0,
    warm_budget_seconds: float = 900.0,
    min_bars: int = 200,
    min_dollar_volume: float = 5_000_000.0,
    max_staleness_days: int = 14,
) -> dict[str, Any]:
    """Discover, optionally warm, and rediscover without weakening gates."""
    path = Path(output)
    initial = discover_equity_candidates(
        domains=domains,
        min_bars=min_bars,
        min_dollar_volume=min_dollar_volume,
        max_staleness_days=max_staleness_days,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(initial, ensure_ascii=False, indent=2) + "\n")

    warm_results: list[dict[str, Any]] = []
    if warm_symbols_per_domain > 0:
        for domain in domains:
            warm_results.append(
                warm_batch(
                    initial,
                    domain=domain,
                    max_symbols=warm_symbols_per_domain,
                    min_interval_seconds=warm_interval_seconds,
                    budget_seconds=warm_budget_seconds,
                )
            )

    final = discover_equity_candidates(
        domains=domains,
        min_bars=min_bars,
        min_dollar_volume=min_dollar_volume,
        max_staleness_days=max_staleness_days,
    )
    path.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n")
    return {
        "output": str(path),
        "initial_counts": initial["counts"],
        "warm": warm_results,
        "final_counts": final["counts"],
        "provider_errors": final["provider_errors"],
        "real_data_only": True,
        "selection_is_not_promotion": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", action="append", choices=("us_equity", "a_share"))
    parser.add_argument("--output", type=Path, default=Path("data/discovered_equity_universe.json"))
    parser.add_argument("--warm-symbols-per-domain", type=int, default=0)
    parser.add_argument("--warm-interval-seconds", type=float, default=1.0)
    parser.add_argument("--warm-budget-seconds", type=float, default=900.0)
    parser.add_argument("--min-bars", type=int, default=200)
    parser.add_argument("--min-dollar-volume", type=float, default=5_000_000.0)
    parser.add_argument("--max-staleness-days", type=int, default=14)
    args = parser.parse_args()
    result = refresh_universe(
        domains=tuple(args.domain or ("us_equity", "a_share")),
        output=args.output,
        warm_symbols_per_domain=args.warm_symbols_per_domain,
        warm_interval_seconds=args.warm_interval_seconds,
        warm_budget_seconds=args.warm_budget_seconds,
        min_bars=args.min_bars,
        min_dollar_volume=args.min_dollar_volume,
        max_staleness_days=args.max_staleness_days,
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
