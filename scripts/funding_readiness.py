"""Generate the real-data funding-rate readiness report."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from libs.quant.funding_readiness import assess_store


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/funding_data_readiness.json"))
    parser.add_argument("--min-observations", type=int, default=252)
    parser.add_argument("--min-span-days", type=int, default=365)
    parser.add_argument("--min-fold-observations", type=int, default=40)
    parser.add_argument("--required-folds", type=int, default=4)
    args = parser.parse_args()
    report = assess_store(
        min_observations=args.min_observations,
        min_span_days=args.min_span_days,
        min_fold_observations=args.min_fold_observations,
        required_folds=args.required_folds,
    )
    report["generated_at"] = datetime.now(UTC).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    coverage = report["coverage"]
    print(
        f"funding readiness={report['status']} symbols={coverage['symbols']} rows={coverage['rows']} "
        f"coverage={coverage['start']}..{coverage['end']} ready={len(report['ready_symbols'])}"
    )
    if report["reason"]:
        print(f"blocked: {report['reason']}")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
