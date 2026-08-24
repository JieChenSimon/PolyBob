"""Reproducible statistical audit for the BTC 5-minute mispricing evidence.

This is an audit/report generator, not a trading backtest.  It deliberately
keeps raw event count separate from calendar independence, and returns
``UNKNOWN`` whenever a temporal split cannot support the pre-registered
cluster floor.  A positive mean or a positive wild-bootstrap result therefore
cannot bypass the evidence gate.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from libs.quant.clustered_inference import analyse
from libs.quant.event_study_board import MIN_CLUSTERS
from libs.quant.hypothesis import HypothesisRegistry
from libs.quant.pbo import deflated_t_stat_threshold


def _status(value: str) -> str:
    return value.upper()


def _events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = payload.get("result", payload)
    rows = result.get("events", []) if isinstance(result, dict) else []
    return [r for r in rows if isinstance(r, dict) and r.get("date") and r.get("excess") is not None]


def _partition(labels: list[str]) -> dict[str, list[str]]:
    """Chronological 60/20/20 split on unique calendar labels."""
    unique = sorted(set(labels))
    if len(unique) < 3:
        return {"train": [], "validation": [], "test": []}
    n = len(unique)
    cut1 = max(1, int(np.floor(n * 0.6)))
    cut2 = max(cut1 + 1, int(np.floor(n * 0.8)))
    cut2 = min(cut2, n - 1)
    return {"train": unique[:cut1], "validation": unique[cut1:cut2], "test": unique[cut2:]}


def _inference(rows: Iterable[dict[str, Any]], hurdle: float) -> dict[str, Any]:
    rows = list(rows)
    result = analyse(
        [float(r["excess"]) for r in rows], [str(r["date"]) for r in rows],
        t_hurdle=hurdle, hold_days=1, cluster_by="day", min_clusters=MIN_CLUSTERS,
        bootstrap_draws=1000, wild_draws=1999, seed=20260825,
    )
    return {
        "status": _status(result.evidence_status), "n": result.n,
        "n_clusters": result.n_clusters, "mean_pct": round(result.mean * 100, 3),
        "median_pct": round(result.median * 100, 3),
        "t_clustered": round(result.t_clustered, 3), "t_iid": round(result.t_iid, 3),
        "wild_p": result.wild_p, "p_floor": result.p_floor,
        "resolvable": result.resolvable, "sign_test_p": result.sign_test_p,
        "bootstrap_ci_pct": None if result.bootstrap_lo is None else [
            round(result.bootstrap_lo * 100, 3), round(result.bootstrap_hi * 100, 3)
        ],
        "warnings": result.warnings,
    }


def _split_audit(rows: list[dict[str, Any]], field: str, hurdle: float) -> dict[str, Any]:
    labels = [str(r["date"])[:7] if field == "month" else str(r["date"])[:10] for r in rows]
    parts = _partition(labels)
    output: dict[str, Any] = {"unit": field, "available": bool(parts["test"]), "partitions": {}}
    for name, allowed in parts.items():
        selected = [r for r in rows if (str(r["date"])[:7] if field == "month" else str(r["date"])[:10]) in allowed]
        item = _inference(selected, hurdle) if selected else {"status": "UNKNOWN", "n": 0, "n_clusters": 0}
        item["labels"] = allowed
        output["partitions"][name] = item
    if not parts["test"]:
        output["status"] = "UNKNOWN"
        output["reason"] = f"need at least 3 independent {field} labels for train-validation-test"
        return output
    adequate = all(output["partitions"][name]["n_clusters"] >= MIN_CLUSTERS for name in ("train", "validation", "test"))
    same_sign = all(output["partitions"][name].get("mean_pct", 0) > 0 for name in ("train", "validation", "test"))
    output["status"] = "PASS" if adequate and same_sign else "UNKNOWN"
    output["reason"] = (
        "all partitions meet cluster floor and preserve sign" if output["status"] == "PASS"
        else f"each partition needs >= {MIN_CLUSTERS} independent clusters; positive sign alone is insufficient"
    )
    return output


def _drawdown(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Diagnostic additive per-contract drawdown; not a capital/P&L execution curve."""
    equity, peak, max_dd = 1.0, 1.0, 0.0
    trough = None
    for row in sorted(rows, key=lambda r: (str(r["date"]), str(r.get("entry_price", "")))):
        equity += float(row["excess"])
        peak = max(peak, equity)
        dd = (peak - equity) / peak if peak > 0 else None
        if dd is not None and dd > max_dd:
            max_dd, trough = dd, str(row["date"])
    return {
        "status": "UNKNOWN", "max_drawdown": round(max_dd, 6), "trough_date": trough,
        "threshold": None, "threshold_status": "NOT_SPECIFIED",
        "basis": "one additive unit stake per event; no overlap, capital, sizing, or fill model",
        "reason": "drawdown is reported diagnostically; no pre-registered BTC drawdown limit is wired into PromotionGate",
    }


def audit(payload: dict[str, Any], *, n_trials: int | None = None) -> dict[str, Any]:
    rows = _events(payload)
    registry_trials = n_trials or HypothesisRegistry().n_trials
    hurdle = deflated_t_stat_threshold(registry_trials)
    overall = _inference(rows, hurdle)
    dates = sorted({str(r["date"])[:10] for r in rows})
    months = sorted({str(r["date"])[:7] for r in rows})
    date_split = _split_audit(rows, "date", hurdle)
    month_split = _split_audit(rows, "month", hurdle)
    oos = date_split["partitions"].get("test", {"status": "UNKNOWN", "n": 0, "n_clusters": 0})
    multiple = {
        "n_trials": registry_trials, "t_hurdle": round(hurdle, 4),
        "status": "APPLIED", "pbo": {"status": "NOT_APPLICABLE", "reason": "one fixed BTC rule; no candidate return matrix"},
    }
    gates = {
        "cluster_inference": overall["status"],
        "wild_bootstrap": "PASS" if overall["status"] == "PASS" and overall.get("wild_p") is not None else "UNKNOWN",
        "date_train_validation_test": date_split["status"], "month_train_validation_test": month_split["status"],
        "oos_stability": "PASS" if date_split["status"] == "PASS" and oos["status"] == "PASS" else "UNKNOWN",
        "drawdown": "UNKNOWN", "return_target": "UNKNOWN" if len(months) < 12 else "NOT_EVALUATED",
    }
    promotion = "PASS" if all(v == "PASS" for v in gates.values()) else "UNKNOWN"
    return {
        "schema_version": "btc5m-statistical-audit-v1", "strategy": "btc5m_mispricing",
        "source_collection_status": payload.get("collection_status"), "real_data_only": payload.get("real_data_only"),
        "n_events": len(rows), "independent_dates": dates, "independent_months": months,
        "overall": overall, "multiple_testing": multiple, "date_split": date_split,
        "month_split": month_split, "oos": oos, "drawdown": _drawdown(rows),
        "gates": gates, "promotion_status": promotion,
        "limitations": [
            "event report stores date, not an exact decision timestamp; ordering is date plus entry price",
            "month split is unavailable until at least three independent months exist, and return targets need twelve complete months",
            "wild bootstrap p is reported but cannot override the cluster floor or unresolved p resolution",
            "drawdown has no pre-registered BTC threshold and is not a fill-accurate portfolio curve",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    gates = report["gates"]
    return "\n".join([
        "# BTC 5m statistical audit",
        "",
        f"结论：**{report['promotion_status']}**。正收益不等于可推广；当前门禁必须保持 UNKNOWN。",
        "",
        f"- 事件数：{report['n_events']}；独立日期：{len(report['independent_dates'])}；独立月份：{len(report['independent_months'])}",
        f"- 聚类 t：{report['overall'].get('t_clustered')}；wild bootstrap p：{report['overall'].get('wild_p')}；p floor：{report['overall'].get('p_floor')}",
        f"- 多重检验：{report['multiple_testing']['n_trials']} trials；t hurdle：{report['multiple_testing']['t_hurdle']}",
        "",
        "## 门禁",
        "",
        *[f"- {name}: {value}" for name, value in gates.items()],
        "",
        "## 缺失/降级",
        "",
        *[f"- {item}" for item in report["limitations"]],
        "",
        "## 判定原则",
        "",
        "日期与月份均按独立日历标签切分，先切分再做聚类推断；任何分区少于 20 个独立簇均为 UNKNOWN。wild bootstrap、正均值和正 OOS 均不能绕过该门禁。",
        "",
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/btc5m_mispricing.json"))
    parser.add_argument("--json-output", type=Path, default=Path("data/btc5m_statistical_audit.json"))
    parser.add_argument("--markdown-output", type=Path, default=Path("reports/btc5m-statistical-audit.md"))
    args = parser.parse_args()
    report = audit(json.loads(args.input.read_text()))
    args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text(render_markdown(report))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
