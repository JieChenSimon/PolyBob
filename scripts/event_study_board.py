"""Regenerate ``data/promotion_board.json`` from the committed experiment output.

This is the only writer of the promotion board. Run it after any experiment
re-runs; it reads the raw result files, recomputes the t-hurdle at the current
trial count, and writes the board. Nothing is typed in by hand — if a row is not
in a raw file, it does not make the board.

    conda run -n polybob python scripts/event_study_board.py [--check]

``--check`` regenerates without writing and exits non-zero if the committed
board differs, which is what CI and the test suite use to keep the board honest.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from libs.quant.event_study_board import BOARD_PATH, Role, build_board, write_board
from libs.quant.hypothesis import HypothesisRegistry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="verify the committed board matches the evidence")
    args = parser.parse_args()

    registry = HypothesisRegistry()
    n_trials = registry.n_trials
    board = build_board(n_trials)

    untested = registry.untested
    print("=" * 90)
    print("PROMOTION BOARD — 从原始实验输出重建")
    print("=" * 90)
    print(f"累计试验(含参数网格) = {n_trials}   t 门槛 = {board['t_hurdle']}")
    if untested:
        print(f"已预注册但无结果(仍计入试验次数): {', '.join(untested)}")
    print()
    print(f"{'strategy':28} {'instrument':12} {'role':6} {'n':>7} {'win%':>6} "
          f"{'mean%':>8} {'t':>7}  结论")
    for row in board["board"]:
        win = row.get("win_rate")
        mean = row.get("mean_excess_pct")
        verdict = "✅ 通过" if row["approved"] else f"🔒 lab ({', '.join(row['failed'])})"
        print(f"{row['strategy']:28} {row['instrument']:12} {row['role']:6} "
              f"{row.get('n') or 0:>7} {(win or 0)*100:>5.1f}% {(mean if mean is not None else 0):>7.2f}% "
              f"{row.get('t_stat') or 0:>7.2f}  {verdict}")

    counts = board["counts"]
    print(f"\n可开仓的边 {counts['approved_trade']} 条;回避过滤器 {counts['approved_avoid']} 条;"
          f"共评估 {counts['total']} 条")
    for row in board["board"]:
        if row["approved"] and row["role"] == Role.AVOID.value:
            print(f"  提醒:{row['strategy']} 是回避过滤器,不产生收益,不授予开仓权限。")

    rendered = json.dumps(board, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        current = Path(BOARD_PATH).read_text() if Path(BOARD_PATH).exists() else ""
        if current != rendered:
            print(f"\n❌ {BOARD_PATH} 与证据不一致,请重新生成。")
            return 1
        print(f"\n✅ {BOARD_PATH} 与证据一致。")
        return 0

    out = write_board(board)
    print(f"\n写入 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
