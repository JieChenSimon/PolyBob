"""Apply the canonical PromotionGate to insider Paper Lab equity curves."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from libs.quant.promotion import PromotionGate, annualized_sharpe


def daily_returns(report: dict) -> np.ndarray:
    curve = report.get("equity_curve", [])
    values = np.asarray([float(point["equity"]) for point in curve], dtype=float)
    if len(values) < 2 or np.any(values[:-1] <= 0):
        return np.asarray([], dtype=float)
    return values[1:] / values[:-1] - 1.0


def main() -> int:
    candidates = {
        "original_equal_exposure": {
            1.0: Path("data/insider_kernel_replay_original_unlevered.json"),
            2.0: Path("data/insider_kernel_replay_original_unlevered_2x.json"),
            3.0: Path("data/insider_kernel_replay_original_unlevered_3x.json"),
        },
        "market20_equal_exposure": {
            1.0: Path("data/insider_kernel_replay_original_market20_equal_exposure.json"),
            2.0: Path("data/insider_kernel_replay_original_market20_equal_exposure_2x.json"),
            3.0: Path("data/insider_kernel_replay_original_market20_equal_exposure_3x.json"),
        },
        "market20_extended_history": {
            1.0: Path("data/insider_kernel_replay_extended_market20.json"),
            2.0: Path("data/insider_kernel_replay_extended_market20_2x.json"),
            3.0: Path("data/insider_kernel_replay_extended_market20_3x.json"),
        },
        "market20_extended_hold30_cap1x": {
            1.0: Path("data/insider_kernel_replay_extended_market20_hold30_cap1x.json"),
            2.0: Path("data/insider_kernel_replay_extended_market20_hold30_cap1x_2x.json"),
            3.0: Path("data/insider_kernel_replay_extended_market20_hold30_cap1x_3x.json"),
        },
        "market20_extended_hold10_cap1x": {
            1.0: Path("data/insider_kernel_replay_extended_market20_hold10_cap1x.json"),
            2.0: Path("data/insider_kernel_replay_extended_market20_hold10_cap1x_2x.json"),
            3.0: Path("data/insider_kernel_replay_extended_market20_hold10_cap1x_3x.json"),
        },
        "market20_extended_hold30_min100k_cap1x": {
            1.0: Path("data/insider_kernel_replay_extended_market20_hold30_min100k_cap1x.json"),
            2.0: Path("data/insider_kernel_replay_extended_market20_hold30_min100k_cap1x_2x.json"),
            3.0: Path("data/insider_kernel_replay_extended_market20_hold30_min100k_cap1x_3x.json"),
        },
    }
    audits = {}
    for name, cost_paths in candidates.items():
        reports = {multiple: json.loads(path.read_text()) for multiple, path in cost_paths.items()}
        returns = {multiple: daily_returns(report) for multiple, report in reports.items()}
        base = returns[1.0]
        fold_returns = [float(fold["oos_return"]) for fold in reports[1.0]["folds"]]
        stability = sum(value > 0 for value in fold_returns) / len(fold_returns)
        n_trials = 324 if name in {"market20_extended_hold30_cap1x", "market20_extended_hold10_cap1x", "market20_extended_hold30_min100k_cap1x"} else int(
            reports[1.0].get("candidate_family_size", 18)
        )
        gate = PromotionGate(
            n_trials=n_trials,
            min_dsr=0.95,
            min_observations=60,
            min_oos_stability_rate=0.75,
            cost_min_sharpe=0.5,
            periods_per_year=252,
        )
        decision = gate.evaluate(
            base,
            cost_returns_fn=lambda multiple: returns[float(multiple)],
            cost_multiples=(1.0, 2.0, 3.0),
            oos_stability_rate=stability,
        )
        audits[name] = {
            "source_reports": {str(multiple): str(path) for multiple, path in cost_paths.items()},
            "candidate_family_size": n_trials,
            "daily_observations": len(base),
            "base_annualized_sharpe": annualized_sharpe(base),
            "cost_annualized_sharpe": {
                str(multiple): annualized_sharpe(values) for multiple, values in returns.items()
            },
            "oos_fold_returns": fold_returns,
            "oos_stability_rate": stability,
            "promotion": decision.to_dict(),
            "status": "replay_only_not_promoted",
        }
    report = {"real_data_only": True, "candidates": audits,
              "status": "replay_only_not_promoted"}
    out = Path("data/insider_promotion_audit.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
