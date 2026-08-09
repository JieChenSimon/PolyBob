"""Backfill the searches this project ran and did not count as trials.

The t-hurdle is ``deflated_t_stat_threshold(n_trials)``, and ``n_trials`` counted
only what somebody remembered to call ``register()`` on. Two real searches were
never registered:

1. **The wide chart-pattern sweep — 184 configurations.** Referenced in four
   places in the codebase as the reason chart patterns are treated as unvalidated
   ("184 tested configurations, none confirmed"). It is cited as evidence when it
   argues *against* something, and omitted from the trial count where it would
   raise the bar. It cannot be both.

2. **The focused directional board — 18 tests.** 3 domains x 3 edges x 2
   directions, with the winning direction picked by the data. ``focused_scoreboard.py``
   knew this and set its own local ``n_trials = len(tests)``, but that number lived
   inside one script and never reached the registry the event studies read.

Leaving these out is not a rounding error. At 35 trials the hurdle is 3.77; the
honest count is 237, which puts it at 4.20. The two edges that just failed at 3.77
would have had to clear even more, and any future edge is now judged against the
search that actually took place rather than the fraction of it that was logged.

Idempotent: re-running upserts by ``search_id``.
"""

from __future__ import annotations

from libs.quant.hypothesis import HypothesisRegistry
from libs.quant.pbo import deflated_t_stat_threshold

# 3 domains x 3 edges x 2 directions, as constructed in scripts/focused_scoreboard.py.
FOCUSED_BOARD_TESTS = 18

# The sweep cited in strategies/trading_wisdom.py, VerdictBanner.tsx,
# USEquityAdvisor.tsx and focused_scoreboard.py's own docstring.
WIDE_SWEEP_CONFIGS = 184


def main() -> None:
    registry = HypothesisRegistry()
    before = registry.n_trials

    registry.record_search(
        "wide_chart_pattern_sweep",
        WIDE_SWEEP_CONFIGS,
        "宽扫:通用图形形态(区间扩张/缺口/量价确认等)在三个域上的 184 组参数配置。",
        outcome="0 promoted — 本项目多处引用它作为'图形形态未获验证'的依据",
    )
    registry.record_search(
        "focused_directional_board",
        FOCUSED_BOARD_TESTS,
        "定向板:3 个域 x 3 条边 x 双向(follow/fade),方向由数据挑选。",
        outcome="0 promoted — 双向都测,方向不是先验而是搜索结果",
    )

    after = registry.n_trials
    print("=" * 78)
    print("补登此前未计入的搜索")
    print("=" * 78)
    for search in registry.searches:
        print(f"  {search['search_id']:32} {search['n_configs']:>4} 组  {search['outcome']}")
    print()
    print(f"试验次数  {before} -> {after}")
    print(f"t 门槛    {deflated_t_stat_threshold(before):.2f} -> "
          f"{deflated_t_stat_threshold(after):.2f}")
    print("\n下一步:python scripts/event_study_board.py  (门槛变了,看板必须重建)")


if __name__ == "__main__":
    main()
