"""One command from experiment to rebuilt board — with the discipline enforced.

Everything the promotion gate depends on is now checkable, but it is checkable in
five separate steps that a person has to remember in the right order:

    git commit                       # or the run cannot be replayed
    python scripts/insider_experiment.py
    python scripts/event_study_board.py
    python -m pytest
    # ...and notice if the board moved

Forgetting the first step silently produces a result that cannot grant permission.
Forgetting the third leaves the board describing an experiment that no longer
exists. Neither failure announces itself, and both have already happened in this
repository — the board once cited a 44,750-event study that existed in no committed
file.

So this is the loop, in one place:

    python scripts/research.py run insider          # one experiment, then rebuild
    python scripts/research.py run all              # every experiment
    python scripts/research.py status               # what the board says and why
    python scripts/research.py check                # is the board in step? (CI)

It refuses to start on a dirty tree unless you pass ``--allow-dirty``, because a
run whose code is unidentifiable is a run whose result cannot be promoted, and
finding that out *after* an hour of SEC fetches is a waste of an hour.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from libs.data.run_manifest import _code_state, load as load_manifest
from libs.quant.event_study_board import BOARD_PATH
from libs.quant.hypothesis import HypothesisRegistry
from libs.quant.pbo import deflated_t_stat_threshold


@dataclass(frozen=True)
class Experiment:
    key: str
    script: str
    result: str
    label: str
    minutes: str          # rough cost, so a person can choose knowingly


EXPERIMENTS: tuple[Experiment, ...] = (
    Experiment("insider", "scripts/insider_experiment.py",
               "data/insider_results.json", "美股内部人集群买入", "~10 分钟"),
    Experiment("altcoin", "scripts/us_crypto_experiment.py",
               "data/us_crypto_results.json", "山寨币散户拥挤 + 美股内部人卖出", "~3 分钟"),
    Experiment("billboard", "scripts/billboard_experiment.py",
               "data/billboard_results.json", "A股龙虎榜反转", "~15 分钟"),
    # Was missing from this list, which is why its manifest went stale while the other
    # three were re-run on a clean tree. A runner that covers three of four experiments
    # quietly reintroduces the drift it exists to prevent.
    Experiment("btc5m", "scripts/btc5m_mispricing.py",
               "data/btc5m_mispricing.json", "BTC 5分钟模型 vs 市价", "~10 分钟"),
)


def _run(script: str) -> int:
    print(f"\n{'─' * 78}\n▶ {script}\n{'─' * 78}")
    return subprocess.call([sys.executable, script])


def _preflight(allow_dirty: bool) -> bool:
    """Refuse a run whose result could not grant permission anyway."""
    state = _code_state()
    if not state["commit"]:
        print("✗ 不在 git 仓库里 —— 这次运行无法被复现,结果不能授予开仓权限。")
        return allow_dirty
    if state["dirty"]:
        print(f"✗ 有 {state['dirty_files']} 个源码文件未提交:")
        for path in state["dirty_sample"]:
            print(f"    {path}")
        print("\n  记录的 commit 不会描述实际跑的代码,所以这次实验的结果拿不到开仓权限。")
        print("  先 commit 再跑;确实只是想看看数字的话加 --allow-dirty。")
        return allow_dirty
    print(f"✓ 工作区干净 (commit {state['commit'][:8]})")
    return True


def _board() -> dict:
    try:
        return json.loads(BOARD_PATH.read_text())
    except Exception:  # noqa: BLE001
        return {}


def cmd_status(_: argparse.Namespace) -> int:
    registry = HypothesisRegistry()
    board = _board()
    n_trials = registry.n_trials

    print("=" * 78)
    print("研究状态")
    print("=" * 78)
    print(f"累计试验 {n_trials}(含参数网格与放弃的扫描)  →  t 门槛 "
          f"{deflated_t_stat_threshold(n_trials):.2f}")
    if registry.searches:
        print("  其中探索性扫描:")
        for search in registry.searches:
            print(f"    {search['search_id']:32} {search['n_configs']:>4} 组")
    untested = registry.untested
    if untested:
        print(f"  已预注册但无结果(仍计入试验): {', '.join(untested)}")

    print("\n--- 证据文件 ---")
    for exp in EXPERIMENTS:
        path = Path(exp.result)
        if not path.exists():
            print(f"  ✗ {exp.label:28} 没有结果文件 ({exp.result})")
            continue
        manifest = load_manifest(exp.result)
        if manifest is None:
            print(f"  ⚠ {exp.label:28} 有结果但没有运行清单 —— 无法重放")
            continue
        mark = "✓" if manifest.reproducible else "⚠"
        note = "" if manifest.reproducible else "  (源码未提交,不能授予开仓权限)"
        print(f"  {mark} {exp.label:28} as_of {manifest.as_of.isoformat()[:19]}{note}")

    rows = board.get("board", [])
    if not rows:
        print("\n没有看板。跑 `python scripts/research.py run all`。")
        return 1

    print(f"\n--- 晋级看板 (门槛 {board.get('t_hurdle')}) ---")
    for row in sorted(rows, key=lambda r: (not r["approved"], r["role"], r["strategy"])):
        verdict = "✅ 通过" if row["approved"] else "🔒 lab"
        t = "—" if row.get("t_stat") is None else f"{row['t_stat']:+.2f}"
        print(f"  {verdict}  {row['strategy']:28} {row['role']:6} "
              f"n={row.get('n') or 0:>6}  t={t:>7}")
        for reason in row.get("failed", []):
            print(f"           └ {reason}")

    counts = board.get("counts", {})
    print(f"\n可开仓 {counts.get('approved_trade', 0)} 条;"
          f"回避过滤器 {counts.get('approved_avoid', 0)} 条")
    if not counts.get("approved_trade"):
        print("\n可开仓的边为 0 —— 这是一个诚实的状态,不是故障。"
              "\n复活路径只有一条:把样本期拉长到覆盖更多独立的行情段。"
              "\n在同一批周里堆更多事件不会改变任何结论。")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    wanted = (list(EXPERIMENTS) if args.which == "all"
              else [e for e in EXPERIMENTS if e.key == args.which])
    if not wanted:
        print(f"未知实验 '{args.which}';可选: all, "
              f"{', '.join(e.key for e in EXPERIMENTS)}")
        return 2

    print("=" * 78)
    print(f"研究运行:{', '.join(e.label for e in wanted)}")
    print("=" * 78)
    if not _preflight(args.allow_dirty):
        return 1
    print("预计耗时:" + "、".join(f"{e.label} {e.minutes}" for e in wanted))

    failed = [e.script for e in wanted if _run(e.script) != 0]
    if failed:
        print(f"\n✗ 实验失败:{', '.join(failed)} —— 不重建看板。")
        return 1

    # Rebuilding is not optional. A result written without regenerating the board
    # leaves the gate describing an experiment that no longer exists, and that
    # divergence is silent.
    print(f"\n{'─' * 78}\n▶ 重建看板\n{'─' * 78}")
    if _run("scripts/event_study_board.py") != 0:
        return 1

    print(f"\n{'=' * 78}")
    return cmd_status(args)


def cmd_check(_: argparse.Namespace) -> int:
    """Is the committed board still what the evidence produces? (CI)"""
    code = subprocess.call([sys.executable, "scripts/event_study_board.py", "--check"])
    if code != 0:
        return code

    # A trade row citing an unreplayable run is a claim, not evidence. The board
    # already refuses to approve one; this reports it as a repository-level fault so
    # it is fixed rather than lived with.
    stale = []
    for exp in EXPERIMENTS:
        if not Path(exp.result).exists():
            continue
        manifest = load_manifest(exp.result)
        if manifest is None or not manifest.reproducible:
            stale.append(exp.label)
    if stale:
        print(f"\n⚠ 这些证据无法重放:{', '.join(stale)}")
        print("  它们不会授予开仓权限。提交源码后重跑可以修复。")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="跑实验并重建看板")
    run.add_argument("which", nargs="?", default="all",
                     help="all 或 " + ", ".join(e.key for e in EXPERIMENTS))
    run.add_argument("--allow-dirty", action="store_true",
                     help="源码未提交也照跑(结果拿不到开仓权限)")
    run.set_defaults(func=cmd_run)

    status = sub.add_parser("status", help="看板现状与原因")
    status.set_defaults(func=cmd_status)

    check = sub.add_parser("check", help="看板是否与证据一致(CI 用)")
    check.set_defaults(func=cmd_check)

    args = parser.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
