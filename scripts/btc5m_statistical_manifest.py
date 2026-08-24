"""Build the unified BTC 5m calibration/direction/event statistical manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from libs.quant.statistical_manifest import build_statistical_manifest, validate_statistical_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration", type=Path, default=Path("data/btc5m_calibration.json"))
    parser.add_argument("--direction", type=Path, default=Path("data/btc5m_direction_kernel_replay.json"))
    parser.add_argument("--event", type=Path, default=Path("data/btc5m_mispricing.json"))
    parser.add_argument("--promotion-board", type=Path, default=Path("data/promotion_board.json"))
    parser.add_argument("--output", type=Path, default=Path("data/btc5m_statistical_manifest.json"))
    args = parser.parse_args()
    board = json.loads(args.promotion_board.read_text()) if args.promotion_board.exists() else {}
    manifest = build_statistical_manifest(
        json.loads(args.calibration.read_text()), json.loads(args.direction.read_text()), json.loads(args.event.read_text()),
        event_n_trials=board.get("n_trials"),
    )
    errors = validate_statistical_manifest(manifest)
    manifest["validation"] = {"status": "PASS" if not errors else "FAIL", "errors": errors}
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
