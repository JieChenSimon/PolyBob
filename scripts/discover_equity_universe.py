"""Generate the autonomous US/A-share candidate manifest.

Examples:
    uv run --locked python scripts/discover_equity_universe.py --domain us_equity --limit 200
    uv run --locked python scripts/discover_equity_universe.py --domain us_equity --domain a_share
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from libs.data.universe_discovery import discover_equity_candidates


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", action="append", choices=("us_equity", "a_share"), default=None)
    parser.add_argument("--limit", type=int, default=None, help="maximum symbols per domain")
    parser.add_argument("--min-bars", type=int, default=200)
    parser.add_argument("--output", type=Path, default=Path("data/discovered_equity_universe.json"))
    args = parser.parse_args()
    result = discover_equity_candidates(
        domains=tuple(args.domain or ("us_equity", "a_share")),
        limit=args.limit,
        min_bars=args.min_bars,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), **result["counts"], "provider_errors": result["provider_errors"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
