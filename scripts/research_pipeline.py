"""Resumable research pipeline: collect, evaluate, and report without false promotion.

Each experiment is run independently so a slow or unavailable provider does not
stop the other research lines.  The command writes a machine-readable run
report, but promotion still comes only from the canonical event-study board.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:  # works both as ``python scripts/research_pipeline.py`` and as a module
    from scripts.research import EXPERIMENTS, _preflight
except ModuleNotFoundError:  # pragma: no cover - exercised by the CLI entrypoint
    from research import EXPERIMENTS, _preflight


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--which", nargs="*", choices=[e.key for e in EXPERIMENTS],
                        default=[e.key for e in EXPERIMENTS])
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--report", default="data/research_pipeline_status.json")
    args = parser.parse_args()
    if not _preflight(args.allow_dirty):
        return 1

    by_key = {e.key: e for e in EXPERIMENTS}
    runs: list[dict[str, object]] = []
    for key in args.which:
        experiment = by_key[key]
        print(f"\n▶ {experiment.label}: {experiment.script}", flush=True)
        completed = subprocess.run(
            [sys.executable, experiment.script],
            check=False,
        )
        result_path = Path(experiment.result)
        runs.append({
            "key": key,
            "script": experiment.script,
            "result": experiment.result,
            "returncode": completed.returncode,
            "result_exists": result_path.exists(),
        })

    # Rebuild even when one source failed: successful completed sources remain
    # auditable, while the board's per-source gates keep incomplete evidence lab-only.
    board_rc = subprocess.run(
        [sys.executable, "scripts/event_study_board.py"], check=False
    ).returncode
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "real_data_only": True,
        "runs": runs,
        "board_returncode": board_rc,
        "promotion_allowed": False,
        "note": "This report orchestrates research only; no live order path exists.",
    }
    target = Path(args.report)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(target)
    failures = [r for r in runs if r["returncode"] != 0]
    print(f"\n流水线完成: {len(runs) - len(failures)}/{len(runs)} 个实验成功；"
          f"失败 {len(failures)} 个；晋级权限=关闭")
    return 1 if failures or board_rc else 0


if __name__ == "__main__":
    raise SystemExit(main())
