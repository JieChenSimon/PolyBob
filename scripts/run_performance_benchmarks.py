#!/usr/bin/env python3
"""Run PolyBob's deterministic hotspot benchmark suite."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.performance.hotspot_benchmarks import run_suite, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scale", choices=("quick", "standard"), default="standard")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--json-output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_suite(scale=args.scale, repeats=args.repeats, warmups=args.warmups)

    print(json.dumps(report["metadata"], indent=2))
    print(
        "\n"
        f"scale={args.scale} repeats={args.repeats} warmups={args.warmups} "
        f"numba_warmup_ms={report['configuration']['numba_warmup_ms']}"
    )
    print(
        f"{'benchmark':<25} {'median ms':>11} {'p95 ms':>10} "
        f"{'throughput/s':>14} {'unit':<8}"
    )
    print("-" * 75)
    for result in report["results"]:
        print(
            f"{result['name']:<25} {result['median_ms']:>11.3f} "
            f"{result['p95_ms']:>10.3f} {result['throughput_per_second']:>14.2f} "
            f"{result['unit']:<8}"
        )

    if args.json_output:
        write_json(report, args.json_output)
        print(f"\nJSON report: {args.json_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
