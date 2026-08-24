"""Validate a recorded real-kernel crypto TSMOM sensitivity report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from libs.quant.tsmom_audit import audit_candidate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, nargs="?", default=Path("data/crypto_tsmom_threshold_sensitivity.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = json.loads(args.input.read_text())
    if report.get("execution_kernel") != "modules.simulation.SimulationService":
        raise SystemExit("refusing non-SimulationService evidence")
    for candidate in report.get("candidates", []):
        candidate["audit"] = audit_candidate(candidate.get("folds", []))
    report["status"] = "all_candidates_rejected" if not any(
        c["audit"]["approved_for_next_stage"] for c in report.get("candidates", [])
    ) else "candidate_requires_next_stage"
    output = args.output or args.input
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
