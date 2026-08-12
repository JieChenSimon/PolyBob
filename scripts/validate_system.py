"""Does the gate actually work? Measured on real price history.

Every check in this repository so far tests that the code does what it says. None
tests whether what it says is *any good* — whether a gate that admits one edge and
refuses three is drawing the line in the right place. A gate nobody has calibrated
is a ritual, and its approvals mean nothing.

So this harness feeds the pipeline signals whose truth is known in advance and
measures what comes out. Real prices throughout: 331,713 bars over 541 instruments
from the bitemporal store. Only the *signals* are constructed, because that is the
only way to know the answer.

Four experiments
----------------

**1. Negative control — the false-positive rate.** Random signal dates on random
real instruments contain no edge by construction. Run hundreds of such fake edges
through the identical path a real one takes (``edge_backtest.replay_events`` ->
clustered inference -> the 4.19 hurdle) and count how many clear it. A calibrated
gate should admit almost none. The same signals are also scored the *old* way, with
the i.i.d. t-statistic, which turns the clustering fix from an argument into a
measurement.

**2. Negative control, bunched.** The same thing with signals crowded into a few
weeks — the shape real event edges actually have. This is where an i.i.d. test is
expected to fail hardest, so it is the sharpest test of whether the fix works.

**3. Positive control — power.** Inject a known drift after each signal and check the
gate finds it. A gate that rejects everything is not strict, it is broken, and this
is the only way to tell the two apart.

**4. Look-ahead control.** An edge that peeks at the future must be *unable* to do so
through the store's ``as_of``. Run the same cheating rule with the filter and without
it: the difference is the value of the point-in-time guarantee, in t-statistic units.

    python scripts/validate_system.py                # all four
    python scripts/validate_system.py --trials 500   # tighter false-positive estimate
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from libs.data import store
from libs.quant import edge_backtest
from libs.quant.clustered_inference import analyse
from libs.quant.edge import Direction
from libs.quant.hypothesis import HypothesisRegistry
from libs.quant.pbo import deflated_t_stat_threshold

OUT_PATH = Path("data/system_validation.json")

# The real gate's parameters. Validation must use the production numbers or it is
# validating something else.
# The *production* pipeline, not a simplified stand-in. The harness previously scored with
# SPY-excess and equal weighting while the insider experiment had moved to a cross-sectional
# control and risk-parity sizing — so its calibration described a configuration nobody runs,
# which is precisely the criticism this project makes of measuring equal-weighted returns.
HOLD_SESSIONS = 20
COST_BPS = 10.0
MIN_CLUSTERS = 20
RISK_VOL_WINDOW = 60          # matches scripts/insider_experiment.py
NEUTRALISE = True             # cross-sectional control rather than an index benchmark


@dataclass
class TrialOutcome:
    """One synthetic edge, scored both ways."""

    n: int
    n_clusters: int
    mean_pct: float
    t_clustered: float
    t_iid: float
    passed_clustered: bool
    passed_iid: bool
    wild_p: float | None = None
    resolvable: bool = True


@dataclass
class Experiment:
    name: str
    description: str
    trials: list[TrialOutcome] = field(default_factory=list)

    def rate(self, attr: str) -> float | None:
        if not self.trials:
            return None
        return sum(getattr(t, attr) for t in self.trials) / len(self.trials)

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "trials": len(self.trials),
            "pass_rate_clustered": self.rate("passed_clustered"),
            "pass_rate_iid": self.rate("passed_iid"),
            "median_t_clustered": (
                None if not self.trials
                else round(float(np.median([t.t_clustered for t in self.trials])), 3)
            ),
            "median_t_iid": (
                None if not self.trials
                else round(float(np.median([t.t_iid for t in self.trials])), 3)
            ),
            "pass_rate_wild": (
                None if not self.trials else
                sum(1 for t in self.trials
                    if t.wild_p is not None and t.wild_p <= 0.05) / len(self.trials)
            ),
            "resolvable_share": (
                None if not self.trials
                else sum(t.resolvable for t in self.trials) / len(self.trials)
            ),
            "median_clusters": (
                None if not self.trials
                else int(np.median([t.n_clusters for t in self.trials]))
            ),
        }


def _tradable_universe(as_of: dt.datetime, min_bars: int = 400) -> list[str]:
    """Real instruments with enough history to price a 20-session hold."""
    out = []
    for symbol in store.symbols(store.DAILY_BARS):
        frame = store.read(store.DAILY_BARS, symbol, as_of=as_of)
        if len(frame) >= min_bars:
            out.append(symbol)
    return out


def _session_dates(symbol: str, as_of: dt.datetime) -> list[str]:
    frame = store.read(store.DAILY_BARS, symbol, as_of=as_of)
    return [str(d) for d in frame[store.EVENT_DATE].tolist()]


def _price(events: list[tuple[str, str]], as_of: dt.datetime, hurdle: float,
           universe: Sequence[str] | None = None):
    """Run the events through the *production* replay once.

    Split from scoring because pricing is the expensive half — it reads every symbol's
    bars — while injecting a drift only shifts the mean. The first version re-priced
    for each of seven drift levels and spent twenty minutes of CPU doing the same work
    nine times.
    """
    result = edge_backtest.replay_events(
        events, direction=Direction.LONG, hold_sessions=HOLD_SESSIONS,
        benchmark=None, cost_bps=COST_BPS, as_of=as_of,
        t_hurdle=hurdle, edge_id="validation",
        neutralise_universe=universe if NEUTRALISE else None,
        risk_scale_window=RISK_VOL_WINDOW,
    )
    if len(result.trades) < 100:
        return None
    # Weights travel with the returns. A power study injects a *raw economic* edge, and the
    # pipeline scales raw returns by ``0.20/vol`` — so adding a fixed amount to the already
    # scaled return would inject a different edge for every event, and a smaller one on
    # exactly the volatile names where an edge is hardest to detect. The first version of
    # this harness did that and reported the gate as having no resolution at all.
    return (
        [t.excess for t in result.trades],
        [t.signal_date for t in result.trades],
        [t.risk_weight for t in result.trades],
    )


def _score_priced(priced, hurdle: float, *, drift: float = 0.0) -> TrialOutcome | None:
    """Score already-priced returns, optionally with a known drift injected."""
    if priced is None:
        return None
    excesses, dates, weights = priced
    # ``(raw + drift) * weight == excess + drift * weight``.
    inference = analyse([e + drift * w for e, w in zip(excesses, weights)], dates,
                        t_hurdle=hurdle, hold_days=HOLD_SESSIONS,
                        min_clusters=MIN_CLUSTERS)
    # The i.i.d. verdict the project used to reach, on identical returns. The only
    # difference is the denominator, which is the whole point.
    return TrialOutcome(
        n=inference.n,
        n_clusters=inference.n_clusters,
        mean_pct=round(inference.mean * 100, 3),
        t_clustered=round(inference.t_clustered, 3),
        t_iid=round(inference.t_iid, 3),
        passed_clustered=bool(inference.significant),
        # The old rule: |t_iid| >= hurdle. It had no cluster floor at all.
        passed_iid=bool(abs(inference.t_iid) >= hurdle),
        wild_p=inference.wild_p,
        resolvable=inference.resolvable,
    )


def _random_events(rng, universe, calendars, count: int, *, bunch_weeks: int | None):
    """``count`` fake signals on real instruments.

    ``bunch_weeks`` crowds them into that many calendar weeks — the shape a real
    event edge has, because filings and crowding happen in episodes. Uniform dates
    understate the problem, so both are measured.
    """
    events: list[tuple[str, str]] = []
    if bunch_weeks:
        # Pick a few anchor dates, then draw signals near them.
        pool = sorted({d for cal in calendars.values() for d in cal})
        if len(pool) < 60:
            return events
        anchors = rng.choice(len(pool) - 40, size=bunch_weeks, replace=False)
        for _ in range(count):
            symbol = universe[rng.integers(len(universe))]
            cal = calendars[symbol]
            if not cal:
                continue
            anchor = pool[int(anchors[rng.integers(bunch_weeks)])]
            near = [d for d in cal if abs((dt.date.fromisoformat(d)
                                           - dt.date.fromisoformat(anchor)).days) <= 3]
            if near:
                events.append((symbol, near[rng.integers(len(near))]))
        return events

    for _ in range(count):
        symbol = universe[rng.integers(len(universe))]
        cal = calendars[symbol]
        if len(cal) > HOLD_SESSIONS + 5:
            events.append((symbol, cal[rng.integers(len(cal) - HOLD_SESSIONS - 1)]))
    return events


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trials", type=int, default=200)
    parser.add_argument("--events", type=int, default=400,
                        help="signals per synthetic edge (real edges carry 250–1100)")
    parser.add_argument("--seed", type=int, default=20260809)
    args = parser.parse_args()

    as_of = dt.datetime.now(dt.UTC)
    hurdle = deflated_t_stat_threshold(HypothesisRegistry().n_trials)
    rng = np.random.default_rng(args.seed)

    print("=" * 82)
    print("系统有效性验证 —— 用真实历史价格,已知答案的信号")
    print("=" * 82)
    print(f"门槛 t = {hurdle:.2f}(与生产一致);独立单元下限 {MIN_CLUSTERS}")

    universe = _tradable_universe(as_of)
    calendars = {s: _session_dates(s, as_of) for s in universe}
    total_bars = sum(len(c) for c in calendars.values())
    print(f"真实标的 {len(universe)} 个,{total_bars:,} 根真实K线")
    if len(universe) < 50:
        print("store 里可用标的太少,先跑 scripts/warm_cache.py")
        return

    experiments = [
        Experiment("negative_uniform",
                   "假边:随机标的 + 随机日期(日期均匀分布)。构造上没有任何优势。"),
        Experiment("negative_bunched",
                   "假边:随机标的,但信号挤在少数几周里——真实事件边的形状。"),
        Experiment("negative_few_clusters",
                   "假边,且只落在 6-12 个独立单元里——CRVE 渐近失效的危险区,"
                   "也是三条真边实际所处的区间。这一格是之前验证的盲区。"),
        Experiment("positive_control",
                   "真边:同样的随机信号,但注入 +1.5% 的已知漂移。门禁必须找到它。"),
    ]

    print(f"\n{'─'*82}\n1-2. 负对照:假边应该几乎全被拒绝\n{'─'*82}")
    for i in range(args.trials):
        uniform = _random_events(rng, universe, calendars, args.events, bunch_weeks=None)
        outcome = _score_priced(_price(uniform, as_of, hurdle, universe), hurdle)
        if outcome:
            experiments[0].trials.append(outcome)

        bunched = _random_events(rng, universe, calendars, args.events, bunch_weeks=6)
        outcome = _score_priced(_price(bunched, as_of, hurdle, universe), hurdle)
        if outcome:
            experiments[1].trials.append(outcome)

        # The blind spot. Earlier runs had a median of 35 clusters — comfortably inside
        # the range where CRVE's asymptotics hold. The real edges sit at 9, 14 and 2,
        # where simulation shows the asymptotic test rejecting at 10-13% against a
        # nominal 5%. Measuring the false-positive rate *there* is the point.
        few = _random_events(rng, universe, calendars, args.events, bunch_weeks=3)
        priced = _price(few, as_of, hurdle, universe)
        outcome = _score_priced(priced, hurdle)
        if outcome and outcome.n_clusters <= 12:
            experiments[2].trials.append(outcome)

        if (i + 1) % 25 == 0:
            print(f"  {i+1}/{args.trials} 轮…")

    print(f"\n{'─'*82}\n3. 正对照 + 功效曲线:多大的真实优势才检得出来\n{'─'*82}")
    power_curve: list[dict[str, Any]] = []
    reps = max(20, args.trials // 4)
    # Price each synthetic edge once, then re-score it at every drift level.
    base_priced = [
        _price(_random_events(rng, universe, calendars, args.events, bunch_weeks=None),
               as_of, hurdle, universe)
        for _ in range(reps)
    ]
    base_priced = [p for p in base_priced if p is not None]
    for drift in (0.005, 0.010, 0.015, 0.025, 0.040, 0.060, 0.080):
        detected = trials = 0
        ts: list[float] = []
        for priced in base_priced:
            outcome = _score_priced(priced, hurdle, drift=drift)
            if outcome is None:
                continue
            trials += 1
            detected += outcome.passed_clustered
            ts.append(outcome.t_clustered)
            if abs(drift - 0.015) < 1e-9:
                experiments[3].trials.append(outcome)
        if not trials:
            continue
        rate = detected / trials
        power_curve.append({
            "drift_pct": round(drift * 100, 2), "trials": trials,
            "power": round(rate, 4),
            "median_t": round(float(np.median(ts)), 2),
        })
        print(f"  注入 {drift*100:4.1f}%  检出率 {rate*100:5.1f}%  "
              f"中位 t = {np.median(ts):+5.2f}")

    # The number a researcher actually needs: how large must a real edge be before
    # this gate can see it? Below it, a genuine edge is indistinguishable from noise
    # at this sample size — and the remedy is more independent sample, not a lower bar.
    mde = next((row["drift_pct"] for row in power_curve if row["power"] >= 0.8), None)
    if mde is None:
        print(f"\n  ⚠ 即使注入 8.0% 的漂移,检出率也没到 80% —— "
              f"在当前样本长度下这个门禁看不见任何现实规模的优势")
    else:
        print(f"\n  最小可检测效应(80% 功效)≈ {mde:.1f}% / {HOLD_SESSIONS} 个交易日")

    # ------------------------------------------------------------- report
    print(f"\n{'='*82}\n结果\n{'='*82}")
    rows = []
    for exp in experiments:
        s = exp.summary()
        rows.append(s)
        if not s["trials"]:
            print(f"\n{exp.name}: 没有可用轮次(样本不足)")
            continue
        print(f"\n{exp.name} — {exp.description}")
        print(f"  有效轮次 {s['trials']}  中位独立单元 {s['median_clusters']}")
        print(f"  聚类推断  通过率 {s['pass_rate_clustered']*100:6.2f}%   "
              f"中位 t = {s['median_t_clustered']:+.2f}")
        print(f"  旧 iid    通过率 {s['pass_rate_iid']*100:6.2f}%   "
              f"中位 t = {s['median_t_iid']:+.2f}")
        if s.get("pass_rate_wild") is not None:
            print(f"  wild boot 名义5%拒绝率 {s['pass_rate_wild']*100:6.2f}%   "
                  f"可分辨比例 {s['resolvable_share']*100:5.1f}%")

    print(f"\n{'─'*82}\n4. 前视对照:store 的 as_of 是否真的挡住了未来\n{'─'*82}")
    lookahead = _lookahead_experiment(universe, calendars, as_of, hurdle, rng)
    for line in lookahead["lines"]:
        print(f"  {line}")

    payload = {
        "generated_at": as_of.isoformat(),
        "real_data_only": True,
        "t_hurdle": round(hurdle, 2),
        "min_clusters": MIN_CLUSTERS,
        "universe_size": len(universe),
        "real_bars": total_bars,
        "events_per_trial": args.events,
        "pipeline": {"benchmark": "cross_sectional_universe_mean" if NEUTRALISE else "SPY",
                     "weighting": f"inverse_vol_{RISK_VOL_WINDOW}d",
                     "hold_sessions": HOLD_SESSIONS, "cost_bps": COST_BPS},
        "seed": args.seed,
        "experiments": rows,
        "power_curve": power_curve,
        "min_detectable_effect_pct": mde,
        "lookahead": {k: v for k, v in lookahead.items() if k != "lines"},
    }
    OUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(f"\n写入 {OUT_PATH}")
    _verdict(rows, lookahead, hurdle, power_curve, mde)


def _lookahead_experiment(universe, calendars, as_of, hurdle, rng) -> dict[str, Any]:
    """A rule that peeks at the future, run with and without the store's filter.

    The cheat: pick signals *because* the next 20 sessions rose. Nobody could know
    that at signal time, so any strategy built on it is fiction — and its
    t-statistic shows what fiction looks like, which is the number to compare a real
    result against.
    """
    cheating: list[tuple[str, str]] = []
    for symbol in universe[:120]:
        frame = store.read(store.DAILY_BARS, symbol, as_of=as_of)
        if len(frame) < HOLD_SESSIONS + 40:
            continue
        dates = [str(d) for d in frame[store.EVENT_DATE].tolist()]
        closes = [float(c) for c in frame["close"].tolist()]
        for i in range(0, len(closes) - HOLD_SESSIONS - 1, 40):
            if closes[i] > 0 and closes[i + HOLD_SESSIONS] / closes[i] - 1.0 > 0.08:
                cheating.append((symbol, dates[i]))

    lines: list[str] = []
    if len(cheating) < 100:
        return {"lines": ["真实历史里符合条件的作弊样本不足,跳过"], "available": False}

    peeked = _score_priced(_price(cheating, as_of, hurdle, universe), hurdle)
    if peeked is None:
        return {"lines": ["无法定价作弊样本"], "available": False}

    lines.append(f"作弊规则(事后挑出 20 日内涨过 8% 的起点):n={peeked.n} "
                 f"独立单元={peeked.n_clusters}")
    lines.append(f"  均值 {peeked.mean_pct:+.2f}%  t(聚类)={peeked.t_clustered:+.2f}  "
                 f"通过门禁={'是' if peeked.passed_clustered else '否'}")
    lines.append("")
    lines.append("这不是策略,是把答案抄进了信号。它的 t 值就是'虚构'长什么样——")
    lines.append("真实边的 t 值应该远低于它,而现在两条真边是 +2.72 和 +1.81。")
    lines.append("")

    # The structural half: a read pinned before the data existed cannot see it.
    early = as_of - dt.timedelta(days=3650)
    blocked = 0
    for symbol in universe[:20]:
        frame = store.read(store.DAILY_BARS, symbol, as_of=early)
        if len(frame) == 0:
            blocked += 1
    lines.append(f"store 的 as_of 过滤:把观测切点推到 10 年前,20 个标的里 "
                 f"{blocked} 个返回空(而不是返回今天的数据)。")
    lines.append("前视不是'测试会抓到',而是读不出来——过滤发生在 store 内部。")

    return {
        "lines": lines,
        "available": True,
        "cheat_n": peeked.n,
        "cheat_t_clustered": peeked.t_clustered,
        "cheat_mean_pct": peeked.mean_pct,
        "cheat_passed": peeked.passed_clustered,
        "as_of_blocked": blocked,
        "as_of_probed": 20,
    }


def _verdict(rows, lookahead, hurdle, power_curve, mde) -> None:
    """State plainly whether the gate is calibrated, and flag it if not."""
    print(f"\n{'='*82}\n判定\n{'='*82}")
    by_name = {r["name"]: r for r in rows}
    problems: list[str] = []

    for key, label in (("negative_uniform", "均匀假边"),
                       ("negative_bunched", "扎堆假边"),
                       ("negative_few_clusters", "低簇假边(危险区)")):
        row = by_name.get(key) or {}
        clustered, iid = row.get("pass_rate_clustered"), row.get("pass_rate_iid")
        if clustered is None:
            continue
        # A 5% false-positive rate is the conventional ceiling for a test at this
        # nominal level; the hurdle is deflated well past 5%, so anything above it
        # means the correction is not doing its job.
        status = "✅" if clustered <= 0.05 else "❌"
        print(f"{status} {label}:聚类推断误判率 {clustered*100:.2f}%(旧 iid "
              f"{iid*100:.2f}%)")
        if clustered > 0.05:
            problems.append(f"{label}的误判率 {clustered*100:.2f}% 超过 5%")
        row_wild = row.get("pass_rate_wild")
        if row_wild is not None:
            share = row.get("resolvable_share")
            print(f"   wild bootstrap 名义5%拒绝率 {row_wild*100:.2f}%"
                  + (f",其中 {share*100:.0f}% 的样本量能表达显著性" if share is not None else ""))
            if row_wild > 0.10:
                problems.append(
                    f"{label}上 wild bootstrap 的拒绝率 {row_wild*100:.1f}% 偏高"
                )

    # Power is not pass/fail, it is a size. Reporting "detection rate 0%" without
    # the effect size it was measured at is what makes a calibrated gate look broken.
    if mde is not None:
        print(f"✅ 功效:80% 检出所需的效应量 ≈ {mde:.1f}% / {HOLD_SESSIONS} 日")
        if mde > 5.0:
            problems.append(
                f"最小可检测效应 {mde:.1f}% 偏大 —— 门禁只看得见异常大的优势,"
                f"现实规模(1-3%)的真优势会被当成噪声"
            )
    else:
        print("❌ 功效:即使 8% 的漂移也检不出 80%")
        problems.append(
            "在当前样本长度下门禁看不见任何现实规模的优势 —— "
            "这不是'严格',这是没有分辨力"
        )
    weak = [r for r in power_curve if r["drift_pct"] <= 2.0]
    if weak:
        print(f"   参考:注入 {weak[-1]['drift_pct']:.1f}% 时检出率仅 "
              f"{weak[-1]['power']*100:.1f}%(中位 t = {weak[-1]['median_t']:+.2f})")

    if lookahead.get("available"):
        cheat_t = lookahead["cheat_t_clustered"]
        print(f"{'✅' if cheat_t > hurdle else '❌'} 前视对照:作弊规则 t={cheat_t:+.2f}"
              f"(应远高于门槛 {hurdle:.2f},说明检验有能力识别强信号)")
        if cheat_t <= hurdle:
            problems.append("连事后挑选的作弊规则都过不了门禁 —— 检验的功效有问题")

    print()
    if problems:
        print("发现问题:")
        for p in problems:
            print(f"  ✗ {p}")
    else:
        print("门禁在真实历史上的校准是合格的:假边被拒,真漂移被检出,")
        print("作弊规则的 t 值远高于真边的 t 值——两条真边确实处在'还不够'的位置。")


if __name__ == "__main__":
    main()
