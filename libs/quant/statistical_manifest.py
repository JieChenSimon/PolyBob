"""Common statistical evidence contract for calibration, direction and event studies.

The three BTC 5m reports were produced by different runners and therefore used
different notions of sample size and OOS evidence.  This module is intentionally
small: it normalizes what each report *actually contains* and marks absent
evidence UNKNOWN.  It never upgrades a positive return into a promotion pass.
"""

from __future__ import annotations

from typing import Any

UNKNOWN = "UNKNOWN"
PASS = "PASS"
FAIL = "FAIL"


def _status(value: Any) -> str:
    value = str(value or UNKNOWN).upper()
    return value if value in {UNKNOWN, PASS, FAIL, "APPLIED", "NOT_APPLICABLE"} else UNKNOWN


def _direction_summary(payload: dict[str, Any]) -> dict[str, Any]:
    results = payload.get("results") or {}
    splits = sorted({str(f.get("split_date")) for r in results.values() for f in r.get("folds", []) if f.get("split_date")})
    promotions = [r.get("promotion") or {} for r in results.values()]
    checks = [c for p in promotions for c in p.get("checks", [])]
    dsr = [c for c in checks if c.get("name") == "deflated_sharpe"]
    cost = [c for c in checks if c.get("name") == "cost_stress"]
    oos = [c for c in checks if c.get("name") == "oos_stability"]
    target_statuses = []
    max_dd = []
    for r in results.values():
        for fold in r.get("folds", []):
            for cost_row in fold.get("costs", []):
                metrics = cost_row.get("metrics") or {}
                if metrics.get("return_target"):
                    target_statuses.append(_status(metrics["return_target"].get("status")))
                if metrics.get("max_drawdown") is not None:
                    max_dd.append(float(metrics["max_drawdown"]))
    return {
        "available": bool(splits), "method": "walk_forward_folds",
        "split_dates": splits, "fold_count": len(splits),
        "status": UNKNOWN if not splits else UNKNOWN,
        "reason": "OOS exists, but no independent-calendar cluster inference is recorded for each fold",
        "cluster_floor": {"status": UNKNOWN, "min_clusters": 20, "observed": None,
                          "reason": "direction report has raw windows/folds, not independent calendar clusters"},
        "drawdown": {"status": UNKNOWN, "max_observed": max(max_dd) if max_dd else None,
                      "threshold": None, "threshold_status": "NOT_SPECIFIED"},
        "return_target": {"status": _status(target_statuses[0]) if target_statuses else UNKNOWN,
                           "observed_statuses": sorted(set(target_statuses)),
                           "reason": "inherits per-fold target result; no promotion upgrade from incomplete months"},
        "multiple_testing": {
            "status": FAIL if dsr and any(not c.get("passed", False) for c in dsr) else UNKNOWN,
            "n_trials": max((int(str(c.get("detail", "0")).split("over ")[1].split(" trial")[0])
                             for c in dsr if "over " in str(c.get("detail", ""))), default=None),
            "dsr_checks": len(dsr), "cost_stress_checks": len(cost),
            "oos_stability_checks": len(oos),
        },
    }


def _calibration_summary(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("rows") or []
    return {
        "available": False, "method": None, "split_dates": [], "fold_count": 0,
        "status": UNKNOWN,
        "reason": "calibration report is a single pooled comparison; it has no train-validation-test or OOS split",
        "cluster_floor": {"status": UNKNOWN, "min_clusters": 20, "observed": payload.get("independent_days"),
                          "reason": "independent day count is reported but no clustered inference is computed"},
        "drawdown": {"status": UNKNOWN, "max_observed": None, "threshold": None, "threshold_status": "NOT_APPLICABLE"},
        "return_target": {"status": UNKNOWN, "reason": "calibration is not a return-target study"},
        "multiple_testing": {"status": UNKNOWN, "n_trials": None,
                              "reason": "no pre-registered trial count or multiplicity correction in calibration report",
                              "rows": len(rows)},
    }


def _event_summary(payload: dict[str, Any], n_trials: int | None = None) -> dict[str, Any]:
    result = payload.get("result") or {}
    split = result.get("time_split") or {}
    period = result.get("period_audit") or {}
    target = period.get("return_target") or {}
    oos = split.get("oos") or {}
    return {
        "available": bool(split), "method": "fixed_chronological",
        "split_dates": [split.get("oos_start")] if split.get("oos_start") else [],
        "fold_count": 1 if split else 0, "status": _status(split.get("status")),
        "reason": "OOS is present but remains UNKNOWN when train/OOS independent days are below the floor or collection is partial",
        "train": split.get("train"), "oos": oos,
        "cluster_floor": {"status": PASS if int(result.get("n_clusters") or 0) >= 20 else UNKNOWN,
                          "min_clusters": 20, "observed": result.get("n_clusters"),
                          "resolvable": result.get("resolvable"),
                          "reason": "cluster floor and p resolution are required independently"},
        "drawdown": {"status": UNKNOWN, "max_observed": period.get("max_drawdown"),
                      "threshold": None, "threshold_status": "NOT_SPECIFIED"},
        "return_target": {"status": _status(target.get("status")),
                           "complete_months": target.get("complete_months"),
                           "required_months": target.get("required_months", 12)},
        "multiple_testing": {"status": "APPLIED" if result.get("t_hurdle") else UNKNOWN,
                              "n_trials": n_trials, "t_hurdle": result.get("t_hurdle"),
                              "wild_p": result.get("wild_p"), "p_floor": result.get("p_floor"),
                              "resolvable": result.get("resolvable")},
    }


def build_statistical_manifest(
    calibration: dict[str, Any], direction: dict[str, Any], event: dict[str, Any],
    *, event_n_trials: int | None = None,
) -> dict[str, Any]:
    """Normalize the three BTC 5m evidence reports into one fail-closed contract."""
    studies = {
        "calibration": _calibration_summary(calibration),
        "direction": _direction_summary(direction),
        "event": _event_summary(event, event_n_trials),
    }
    return {
        "schema_version": "btc5m-statistical-manifest-v1",
        "scope": "BTC 5m research evidence; direction is spot proxy, not Polymarket contract evidence",
        "real_data_only": all(bool(p.get("real_data_only")) for p in (calibration, direction, event)),
        "sources": {
            "calibration": {"generated_at": calibration.get("generated_at"), "status": calibration.get("status")},
            "direction": {"generated_at": direction.get("generated_at"), "status": direction.get("status")},
            "event": {"generated_at": event.get("generated_at"), "collection_status": event.get("collection_status"),
                      "snapshot_status": (event.get("snapshot") or {}).get("status")},
        },
        "studies": studies,
        "unified_gates": {
            "temporal_split": UNKNOWN if any(not s["temporal_split"]["available"] if "temporal_split" in s else not s["available"] for s in studies.values()) else UNKNOWN,
            "oos": UNKNOWN,
            "cluster_floor": UNKNOWN,
            "drawdown": UNKNOWN,
            "return_target": UNKNOWN,
            "multiple_testing": UNKNOWN,
        },
        "promotion_status": UNKNOWN,
        "rules": {
            "min_independent_clusters": 20,
            "min_complete_return_target_months": 12,
            "positive_mean_does_not_pass": True,
            "positive_oos_does_not_pass": True,
            "missing_or_unresolvable_evidence_is_unknown": True,
            "drawdown_requires_preregistered_threshold": True,
        },
    }


def validate_statistical_manifest(manifest: dict[str, Any]) -> list[str]:
    """Return contract violations; an empty list means the manifest is coherent."""
    errors: list[str] = []
    if manifest.get("schema_version") != "btc5m-statistical-manifest-v1":
        errors.append("wrong_schema_version")
    if manifest.get("promotion_status") == PASS:
        errors.append("promotion_must_not_pass_without_all_study_gates")
    rules = manifest.get("rules") or {}
    if rules.get("positive_mean_does_not_pass") is not True:
        errors.append("positive_mean_rule_missing")
    if rules.get("positive_oos_does_not_pass") is not True:
        errors.append("positive_oos_rule_missing")
    for name, study in (manifest.get("studies") or {}).items():
        cluster = study.get("cluster_floor") or {}
        if cluster.get("observed", 0) is not None and cluster.get("observed", 0) < rules.get("min_independent_clusters", 20):
            if cluster.get("status") == PASS:
                errors.append(f"{name}:cluster_floor_passed_below_minimum")
        target = study.get("return_target") or {}
        if target.get("complete_months") is not None and target["complete_months"] < rules.get("min_complete_return_target_months", 12):
            if target.get("status") == PASS:
                errors.append(f"{name}:return_target_passed_with_insufficient_months")
    return errors


__all__ = ["build_statistical_manifest", "validate_statistical_manifest"]
