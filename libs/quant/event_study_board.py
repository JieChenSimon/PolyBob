"""Build the promotion board from the raw experiment outputs — reproducibly.

The board is the file that decides what may reach the execution desk, so the one
property it must have is that anyone can regenerate it and get the same answer.
The previous board did not have it: its rows cited a 44,750-event A-share study
that exists in no committed file, and the two scripts that write
``data/promotion_board.json`` would have replaced those rows with an entirely
different experiment. A gate nobody can reproduce is a claim, not a gate.

So this module makes the board a pure function of three things:

1. **The raw result files** written by the pre-registered experiments. Every
   number on the board is copied from one of them, with the source named.
2. **The canonical trial count** from the hypothesis registry, which now counts
   parameter configurations rather than hypotheses. The t-hurdle is recomputed
   here at that count — never taken from whatever the raw file happened to use
   when it ran, which was a smaller and therefore easier number.
3. **A pre-declared spec per edge**, fixed below: which hypothesis it tests,
   which sign the theory predicted, and — crucially — whether the result is
   *tradable* or only an *avoidance filter*.

That last distinction is the one the old board collapsed. Two of its three
"approved" rows had negative returns: they are reasons not to buy, not sources
of return, and listing them alongside a genuine long signal made the desk look
three edges deep when it was one. :class:`Role` keeps them apart, and
:mod:`libs.quant.promotion_registry` only grants trade permission to ``TRADE``.

**The t-statistic must be cluster-robust.** The board took ``t_stat`` from
whatever the experiment wrote, and every experiment wrote an i.i.d. statistic:
``mean / (sd / sqrt(n))``. In an event study with overlapping holding windows and
events that bunch in calendar time, that denominator is too small — the insider
edge reported t=5.40 where the monthly cluster gives 2.29, and the altcoin short
reported 6.38 where the weekly cluster gives 1.74. Both cleared a 3.77 hurdle on
a statistic that should never have been compared against it. So the board now
**recomputes** the statistic from the per-event returns in the source file
(:mod:`libs.quant.clustered_inference`) rather than copying a number, and a
source that carries no per-event data fails closed: without the dates there is no
way to compute a valid standard error, and an unverifiable t is not evidence.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from libs.data import run_manifest
from libs.quant import clustered_inference
from libs.quant.clustered_inference import ClusteredResult
from libs.quant.pbo import deflated_t_stat_threshold

DATA_DIR = Path("data")
BOARD_PATH = DATA_DIR / "promotion_board.json"


class Role(str, Enum):
    """What a cleared edge entitles you to do."""

    TRADE = "trade"      # a position may be opened on it
    AVOID = "avoid"      # a filter: it says "don't buy", it earns nothing


@dataclass(frozen=True)
class EdgeSpec:
    """A pre-declared mapping from an experiment result to a board row.

    Everything here is fixed *before* the result is read — especially
    ``expected_sign`` and ``role``. A spec written after seeing the numbers is
    how a losing result gets re-labelled into a winner.
    """

    strategy: str            # board id; for TRADE rows this must be a real strategy id
    instrument: str
    domain: str
    hypothesis_id: str       # the pre-registered hypothesis this tests
    source: str              # raw result file, relative to the repo root
    source_strategy: str     # the row label inside that file
    expected_sign: int       # +1 or -1 — the direction the theory predicted
    role: Role
    implementation: str      # how the desk is allowed to act on it
    # How stale the evidence may be before the row loses its permission, measured
    # from the **last event in the study**, not from when the script last ran. A
    # re-run over cached data produces a fresh ``generated_at`` and tells you
    # nothing about whether the finding still describes the current market.
    #
    # These numbers are judgement, not derivation, and are written here rather
    # than buried in a module constant so that changing one is a visible decision.
    # Each is set to roughly twice the data source's own publication cadence: a
    # single cadence of lag is structural and unavoidable, two means nobody has
    # re-measured since the regime could plausibly have turned over.
    max_evidence_age_days: int
    notes: str = ""


# One sample-size floor for every edge, not a number chosen per row. It matches
# the ``min_observations`` the price-based gate already uses
# (:class:`libs.quant.promotion.PromotionGate`), so an event study and a price
# study are held to the same bar. Picking a different threshold per edge is how
# a result gets gated in or out to match what you hoped it would say — the
# multiple-testing correction is what handles significance, and it does that job
# through the t-hurdle, not through a bespoke sample floor.
MIN_OBSERVATIONS = 200

# The floor on *independent* units, which is the sample size that governs the
# standard error. 20 is the conventional lower bound below which cluster-robust
# errors are themselves unreliable — and both current edges sit under it (the
# insider study spans 9 months, the altcoin study 13 weeks), which is why they
# now fail on this line as well as on the t-statistic. The only fix is a longer
# sample period; adding more events inside the same weeks buys nothing.
MIN_CLUSTERS = 20


# The in-scope edges, declared once. Adding a row here is a research decision;
# it must name a pre-registered hypothesis and a raw file that carries the
# result, so a row can never be conjured from a conviction.
EDGE_SPECS: tuple[EdgeSpec, ...] = (
    EdgeSpec(
        strategy="a_share_billboard_reversal",
        instrument="A_SHARE_ALL",
        domain="a_share",
        hypothesis_id="billboard_attention_reversal",
        source="data/billboard_results.json",
        source_strategy="H1 全部上榜(超额,净成本)",
        expected_sign=-1,
        role=Role.AVOID,
        implementation="avoidance_filter_only_no_shorting",
        # 交易所每日公布龙虎榜,没有发布滞后;90 天=约一个季度未复测。
        max_evidence_age_days=90,
        notes="A股个股融券受限,负漂移只能作为回避过滤器,不能作为做空策略。",
    ),
    EdgeSpec(
        strategy="us_insider_cluster_buy",
        instrument="US_ALL",
        domain="us_equity",
        hypothesis_id="insider_cluster_buy",
        source="data/insider_results.json",
        source_strategy="内部人集群买入(≥2人)",
        expected_sign=+1,
        role=Role.TRADE,
        implementation="long_after_cluster_filing",
        # SEC Form 345 批量数据按季度发布,所以一个季度的滞后是结构性的、无法消除的;
        # 180 天意味着已经过了两个季度没人重新测过。
        max_evidence_age_days=180,
        notes="唯一的正收益边:集群买入后按 filing date 建多头。",
    ),
    EdgeSpec(
        strategy="altcoin_retail_crowding",
        instrument="ALTCOIN_x8",
        domain="altcoin",
        hypothesis_id="altcoin_retail_crowding",
        source="data/us_crypto_results.json",
        source_strategy="散户极度做多后 做空(含资金费)",
        expected_sign=+1,     # the SHORT leg's own return, so a real edge is positive
        role=Role.TRADE,
        implementation="short_perp_when_retail_crowded_long",
        # OKX 持仓比例是实时的,没有发布滞后;而且山寨币的市场结构变化最快。
        max_evidence_age_days=90,
        notes="做空腿单独计价并计入资金费,证据和实施方式必须是同一条腿。",
    ),
    EdgeSpec(
        strategy="btc5m_mispricing",
        instrument="BTC_5M",
        domain="btc_5m",
        hypothesis_id="btc5m_model_vs_market",
        source="data/btc5m_mispricing.json",
        source_strategy="btc5m_mispricing",
        expected_sign=+1,
        role=Role.TRADE,
        implementation="take_side_when_model_beats_market_price",
        # 5 分钟盘口,证据每天都在增长;一个月没有新结算就说明这条线已经停了。
        max_evidence_age_days=30,
        notes="旗舰标的:必须和别的边用同一条门槛,不因投入大而放宽。",
    ),
)


def _load_source(path: str | Path) -> dict[str, Any]:
    try:
        return json.loads(Path(path).read_text())
    except Exception:  # noqa: BLE001 - a missing source means no evidence, not a crash
        return {}


def _find_row(payload: dict[str, Any], label: str) -> dict[str, Any] | None:
    """Locate one result row, whether the file holds a list or a single result."""
    rows = payload.get("results")
    if isinstance(rows, list):
        for row in rows:
            if str(row.get("strategy")) == label:
                return row
        return None
    single = payload.get("result")
    if isinstance(single, dict) and str(single.get("strategy")) == label:
        return single
    return None


def _mean_pct(row: dict[str, Any]) -> float | None:
    """The row's effect size in percent, whatever the experiment called it."""
    for key in ("mean_excess_pct", "mean_pnl_per_contract"):
        if row.get(key) is not None:
            return float(row[key])
    return None


def evaluate_spec(
    spec: EdgeSpec,
    payload: dict[str, Any],
    n_trials: int,
    manifest: run_manifest.RunManifest | None = None,
) -> dict[str, Any]:
    """One board row: the raw result judged at the canonical t-hurdle.

    ``manifest`` is passed in rather than read from disk here, so this function
    stays a pure function of its arguments. :func:`build_board` loads it beside the
    source file; a test can hand one over directly.
    """
    hurdle = deflated_t_stat_threshold(n_trials)
    row: dict[str, Any] = {
        "strategy": spec.strategy,
        "instrument": spec.instrument,
        "domain": spec.domain,
        "role": spec.role.value,
        "hypothesis_id": spec.hypothesis_id,
        "source": spec.source,
        "source_strategy": spec.source_strategy,
        "implementation": spec.implementation,
        "expected_sign": spec.expected_sign,
        "t_hurdle": round(hurdle, 2),
        "approved": False,
        "failed": [],
        "notes": spec.notes,
        # Every measurement field is declared here, as ``None``, on every path.
        # The dashboard reads these by name, and a field that is simply absent
        # arrives as ``undefined`` — which slips past a ``!== null`` guard and
        # renders as ``NaN%``. That has already happened once on this project's
        # landing page, so a row that failed early must still be shaped like a row.
        "n": None,
        "win_rate": None,
        "mean_excess_pct": None,
        "median_excess_pct": None,
        "t_stat": None,
        "t_stat_iid": None,
        "n_clusters": None,
        "cluster_by": "",
        "inference": "unverifiable",
        "bootstrap_ci_pct": None,
        "sign_test_p": None,
        "wild_p": None,
        "p_floor": None,
        "resolvable": None,
        "inference_warnings": [],
        # ``evidence_end`` is a fact about the study and never changes.
        # The *age* deliberately is not stored: it changes every day, and a file
        # that must be byte-reproducible cannot hold a value that depends on when
        # you looked. Expiry is enforced at read time instead — see
        # :meth:`libs.quant.promotion_registry.PromotionRegistry.is_promoted`,
        # which is where permission is actually granted and which does know the date.
        "evidence_end": None,
        "max_evidence_age_days": spec.max_evidence_age_days,
        # Provenance: which observation cut produced this row, and whether the
        # code that produced it is identifiable. A result nobody can replay is a
        # claim; the board says which of the two each row is.
        "run_as_of": None,
        "run_reproducible": None,
        "evidence": "",
    }

    result = _find_row(payload, spec.source_strategy)
    if result is None:
        row["failed"] = ["no_result"]
        row["evidence"] = f"{spec.source} 中没有 '{spec.source_strategy}' 这一行"
        return row

    n = int(result.get("n") or 0)
    mean_pct = _mean_pct(result)
    row.update({
        "n": n,
        "win_rate": result.get("win_rate"),
        "mean_excess_pct": mean_pct,
        "median_excess_pct": result.get("median_excess_pct"),
    })

    failed: list[str] = []

    # Recompute the statistic here rather than trusting the file's. This is the
    # one number that decides whether real money may be committed, so the board
    # derives it from the returns themselves at its own hurdle.
    inference = _recompute(spec, payload, result, hurdle)
    if inference is None:
        # No per-event data means no computable standard error. The old files
        # carried a bare i.i.d. ``t_stat`` and the board copied it; accepting that
        # again would restore exactly the flaw this check exists to catch.
        row["failed"] = ["no_per_event_data_cannot_verify_t"]
        row["t_stat"] = None
        row["inference"] = "unverifiable"
        row["evidence"] = (
            f"{spec.source} 未保存逐事件收益与日期,无法计算聚类标准误。"
            "重跑该实验以生成可核验的证据。"
        )
        return row

    row.update({
        "t_stat": round(inference.t_clustered, 2),
        "t_stat_iid": round(inference.t_iid, 2),
        "n_clusters": inference.n_clusters,
        "cluster_by": inference.cluster_by,
        "inference": "cluster_robust",
        "median_excess_pct": round(inference.median * 100, 3),
        "win_rate": round(inference.win_rate, 4),
        "mean_excess_pct": round(inference.mean * 100, 3),
        "bootstrap_ci_pct": (
            None if inference.bootstrap_lo is None
            else [round(inference.bootstrap_lo * 100, 3), round(inference.bootstrap_hi * 100, 3)]
        ),
        "sign_test_p": None if inference.sign_test_p is None else round(inference.sign_test_p, 4),
        # The correctly-sized p (wild cluster bootstrap) and, crucially, the finest p
        # this many clusters can express. Below that floor an edge is not "close to
        # significant" — significance is unrepresentable, which calls for a longer
        # sample rather than another look at the numbers.
        "wild_p": None if inference.wild_p is None else round(inference.wild_p, 5),
        "p_floor": None if inference.p_floor is None else float(f"{inference.p_floor:.3g}"),
        "resolvable": inference.resolvable,
        "inference_warnings": inference.warnings,
    })
    mean_pct = row["mean_excess_pct"]
    n = inference.n

    if n < MIN_OBSERVATIONS:
        failed.append(f"n<{MIN_OBSERVATIONS}")
    if inference.n_clusters < MIN_CLUSTERS:
        # Raw event count is not sample size when the events are dependent. An
        # edge measured over 13 independent weeks has not been tested across
        # enough distinct market conditions, however many events it contains.
        failed.append(f"independent_clusters<{MIN_CLUSTERS}")
    # The pre-registered direction decides the sign. A result that lands the
    # other way falsified the hypothesis; it is not a new edge pointing the
    # other way, and treating it as one is the data-snooping this project
    # already caught itself doing once.
    if mean_pct * spec.expected_sign <= 0:
        failed.append("wrong_sign_vs_preregistration")
    if abs(inference.t_clustered) < hurdle:
        # Two different failures wearing one label. An edge whose cluster count cannot
        # express the required p-value has not been weighed and found wanting; it has
        # not been weighable. The remedy differs — wait for calendar, versus drop the
        # hypothesis — so the board says which.
        if not inference.resolvable:
            failed.append(
                f"unresolvable_at_{inference.n_clusters}_clusters"
            )
        else:
            failed.append(f"|t_clustered|<{hurdle:.2f}")

    # Evidence expires — but expiry is not a property of the evidence, it is a
    # property of *when you ask*. So the board records the boundary of the study
    # and the shelf life the spec declared, and the runtime gate compares them
    # against today. Baking the verdict in here made ``approved`` change on its
    # own overnight, which broke the one guarantee the board has to offer: that
    # rebuilding it from the same evidence yields the same file.
    end = _last_event_date(result)
    if end is not None:
        row["evidence_end"] = end.isoformat()

    # Provenance. A missing manifest means the result predates the discipline and
    # cannot be replayed; a dirty tree means the recorded commit does not describe
    # what ran. Neither is fatal to an *avoid* filter, whose only power is to stop
    # you buying — but neither may grant permission to commit money.
    if manifest is not None:
        row["run_as_of"] = manifest.as_of.isoformat()
        row["run_reproducible"] = manifest.reproducible
    if spec.role is Role.TRADE:
        if manifest is None:
            failed.append("no_run_manifest_cannot_replay")
        elif not manifest.reproducible:
            failed.append("run_not_reproducible_dirty_tree")

    row["failed"] = failed
    row["approved"] = not failed
    row["evidence"] = _evidence(spec, payload, result, inference)
    return row


def _today() -> dt.date:
    return dt.datetime.now(dt.UTC).date()


def _last_event_date(result: dict[str, Any]) -> dt.date | None:
    """The most recent event the study observed — its true evidence boundary."""
    events = result.get("events")
    if not isinstance(events, list) or not events:
        return None
    dates = []
    for event in events:
        raw = (event or {}).get("date")
        if not raw:
            continue
        try:
            dates.append(dt.date.fromisoformat(str(raw)[:10]))
        except ValueError:
            continue
    return max(dates) if dates else None


def _recompute(
    spec: EdgeSpec, payload: dict[str, Any], result: dict[str, Any], hurdle: float
) -> ClusteredResult | None:
    """The row's statistic, computed here from the per-event returns.

    Returns ``None`` when the source file has no ``events`` array — which is the
    signal that the result predates cluster-robust inference and cannot be
    verified. The caller fails the row rather than falling back to the file's own
    number.
    """
    events = result.get("events")
    if not isinstance(events, list) or not events:
        return None
    pairs = [
        (float(e["excess"]), str(e["date"]))
        for e in events
        if isinstance(e, dict) and e.get("excess") is not None and e.get("date")
    ]
    if not pairs:
        return None
    hold = int(payload.get("hold_days") or 0)
    return clustered_inference.analyse(
        [r for r, _ in pairs], [d for _, d in pairs],
        t_hurdle=hurdle, hold_days=hold, min_clusters=MIN_CLUSTERS,
    )


def _evidence(
    spec: EdgeSpec,
    payload: dict[str, Any],
    result: dict[str, Any],
    inference: ClusteredResult,
) -> str:
    """A citation built from the file, so it cannot drift from the numbers."""
    bits = [
        f"来源 {spec.source}",
        f"n={inference.n}",
        f"独立{inference.cluster_by}={inference.n_clusters}",
        f"t(聚类)={inference.t_clustered:.2f} vs t(iid)={inference.t_iid:.2f}",
    ]
    end = _last_event_date(result)
    if end is not None:
        bits.append(f"证据截至 {end.isoformat()}")
    coverage = payload.get("coverage") or {}
    if coverage.get("start") and coverage.get("end"):
        bits.append(f"{coverage['start']}..{coverage['end']}")
    if payload.get("quarters"):
        quarters = payload["quarters"]
        bits.append(f"{quarters[0][0]}Q{quarters[0][1]}..{quarters[-1][0]}Q{quarters[-1][1]}")
    if payload.get("hold_days"):
        bits.append(f"持有 {payload['hold_days']} 日")
    by_year = payload.get("by_year") or {}
    if by_year:
        rates = [v["win_rate"] for v in by_year.values()]
        bits.append(f"逐年胜率 {min(rates)*100:.1f}-{max(rates)*100:.1f}%")
    return "; ".join(bits)


def build_board(n_trials: int, specs: tuple[EdgeSpec, ...] = EDGE_SPECS) -> dict[str, Any]:
    """The whole board, derived from the committed raw files and nothing else."""
    payloads = {spec.source: _load_source(spec.source) for spec in specs}
    manifests = {spec.source: run_manifest.load(spec.source) for spec in specs}
    rows = [
        evaluate_spec(spec, payloads[spec.source], n_trials, manifests[spec.source])
        for spec in specs
    ]
    rows.sort(key=lambda r: (not r["approved"], r["role"], r["strategy"]))

    # Reproducibility: the board is stamped with its inputs, not with "now", so
    # rebuilding from the same evidence yields the same file.
    sources = {
        path: (payload.get("generated_at") or "missing")
        for path, payload in sorted(payloads.items())
    }
    generated_at = max((v for v in sources.values() if v != "missing"), default="")

    approved = [r for r in rows if r["approved"]]
    return {
        "generated_at": generated_at,
        "real_data_only": True,
        "n_trials": n_trials,
        "t_hurdle": round(deflated_t_stat_threshold(n_trials), 2),
        "sources": sources,
        "note": (
            "由 scripts/event_study_board.py 从原始实验输出生成;每行的 t 值都是本模块"
            "用 source 文件里的逐事件收益重算的聚类标准误 t,不是抄来的。"
            "role=trade 才可开仓,role=avoid 只是回避过滤器。"
        ),
        "inference": "cluster_robust",
        "min_clusters": MIN_CLUSTERS,
        "counts": {
            "approved_trade": sum(1 for r in approved if r["role"] == Role.TRADE.value),
            "approved_avoid": sum(1 for r in approved if r["role"] == Role.AVOID.value),
            "total": len(rows),
        },
        "board": rows,
    }


def write_board(board: dict[str, Any], path: str | Path = BOARD_PATH) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(board, indent=2, ensure_ascii=False) + "\n")
    return out


__all__ = [
    "BOARD_PATH",
    "EDGE_SPECS",
    "EdgeSpec",
    "Role",
    "build_board",
    "evaluate_spec",
    "write_board",
]
