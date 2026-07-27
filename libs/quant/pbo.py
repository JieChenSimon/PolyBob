"""Probability of Backtest Overfitting (PBO) via CSCV.

The deflated Sharpe ratio asks "is this Sharpe real given N trials?". PBO asks a
different and equally important question: **if I select the best configuration
in-sample, how often does it underperform the median out-of-sample?** Bailey &
López de Prado showed standard validation badly underestimates this danger and
proposed Combinatorially Symmetric Cross-Validation (CSCV) to measure it.

Method: split the return series into ``S`` equal blocks, form every way of
choosing ``S/2`` blocks as the in-sample set (the complement is out-of-sample),
pick the configuration with the best in-sample Sharpe, then record its
out-of-sample *rank*. PBO is the share of splits where that winner lands in the
bottom half out-of-sample. PBO near 0.5 means selection carries no information —
the backtest is a coin flip dressed up as research.

Interpretation used here: ``PBO <= 0.10`` credible, ``<= 0.25`` acceptable,
``> 0.50`` the strategy selection is overfit.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np


def _sharpe(returns: np.ndarray) -> float:
    if len(returns) < 2:
        return 0.0
    sd = returns.std(ddof=1)
    return 0.0 if sd == 0 else float(returns.mean() / sd)


@dataclass(frozen=True)
class PBOResult:
    pbo: float                 # probability of backtest overfitting, 0..1
    n_splits: int
    median_oos_rank: float     # 0 = best, 1 = worst
    verdict: str

    def to_dict(self) -> dict:
        return {
            "pbo": round(self.pbo, 4),
            "n_splits": self.n_splits,
            "median_oos_rank": round(self.median_oos_rank, 4),
            "verdict": self.verdict,
        }


def probability_of_backtest_overfitting(
    returns_matrix: np.ndarray, n_blocks: int = 10
) -> PBOResult:
    """CSCV PBO for a matrix of candidate strategies.

    ``returns_matrix`` is ``(n_configs, n_periods)`` — one row per candidate
    configuration, all evaluated on the same periods. Needs at least two
    configurations: PBO is a statement about *selection*, so a single strategy
    has nothing to select between.
    """
    matrix = np.asarray(returns_matrix, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] < 2:
        raise ValueError("PBO needs a (n_configs, n_periods) matrix with >= 2 configs")

    n_configs, n_periods = matrix.shape
    if n_blocks % 2 != 0:
        n_blocks -= 1
    n_blocks = max(4, min(n_blocks, n_periods // 5))
    if n_blocks < 4:
        raise ValueError("not enough periods for CSCV")

    edges = np.array_split(np.arange(n_periods), n_blocks)
    half = n_blocks // 2
    ranks: list[float] = []

    for in_blocks in combinations(range(n_blocks), half):
        out_blocks = [b for b in range(n_blocks) if b not in in_blocks]
        in_idx = np.concatenate([edges[b] for b in in_blocks])
        out_idx = np.concatenate([edges[b] for b in out_blocks])

        in_sharpes = np.array([_sharpe(matrix[c, in_idx]) for c in range(n_configs)])
        out_sharpes = np.array([_sharpe(matrix[c, out_idx]) for c in range(n_configs)])

        best = int(np.argmax(in_sharpes))
        # Relative rank of the in-sample winner among out-of-sample results.
        order = np.argsort(out_sharpes)            # ascending
        position = int(np.where(order == best)[0][0])
        ranks.append(1.0 - position / max(n_configs - 1, 1))   # 0 best, 1 worst

    ranks_arr = np.asarray(ranks)
    pbo = float((ranks_arr > 0.5).mean())          # winner fell to bottom half
    if pbo <= 0.10:
        verdict = "credible"
    elif pbo <= 0.25:
        verdict = "acceptable"
    elif pbo <= 0.50:
        verdict = "suspect"
    else:
        verdict = "overfit"
    return PBOResult(pbo, len(ranks), float(np.median(ranks_arr)), verdict)


def deflated_t_stat_threshold(n_trials: int, base: float = 3.0) -> float:
    """Minimum |t| a candidate must clear given the size of the search.

    The factor-zoo literature raised the bar from t=2.0 to t>=3.0 precisely
    because of multiple testing; this grows it further with the trial count.
    """
    if n_trials <= 1:
        return base
    return float(base + 0.5 * np.log10(n_trials))


__all__ = [
    "PBOResult",
    "deflated_t_stat_threshold",
    "probability_of_backtest_overfitting",
]
