"""Ensemble combiner: how the strategies are combined into one sized decision.

Blending alphas well is its own discipline. This module follows two
well-established ideas:

1. **Risk-parity / inverse-volatility weighting** — combine heterogeneous
   directional signals weighted by inverse risk contribution, so a single noisy
   strategy cannot dominate the book.
2. **Meta-labeling** (López de Prado) — separate *direction* from *size*. The
   primaries decide direction; a secondary gate decides how big to go and
   filters false positives. Sizing uses the empirical CDF of past confidence
   (the documented right way) rather than raw model confidence, then is scaled
   down by a volatility target, a fractional-Kelly cap, and — for
   prediction-market legs — the favorite-longshot discipline.

The result is a single ``EnsembleDecision`` (direction, size in [0, 1], and the
reasons), which downstream execution/sizing can act on.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field

import numpy as np

from strategies.prediction_market_edges import longshot_size_scale


def inverse_volatility_weights(vols) -> np.ndarray:
    """Weights proportional to 1/volatility, summing to 1 (risk parity, diagonal)."""
    v = np.asarray(vols, dtype=float)
    if v.size == 0:
        return v
    inv = np.where(v > 0, 1.0 / v, 0.0)
    total = inv.sum()
    if total <= 0:
        return np.full(v.shape, 1.0 / v.size)
    return inv / total


def risk_parity_combine(signals, vols) -> float:
    """Inverse-vol-weighted blend of directional signals, result in [-1, 1]."""
    s = np.asarray(signals, dtype=float)
    if s.size == 0:
        return 0.0
    weights = inverse_volatility_weights(vols)
    return float(np.clip(np.dot(weights, s), -1.0, 1.0))


def fractional_kelly(edge: float, *, fraction: float = 0.25, cap: float = 0.5) -> float:
    """A conservative Kelly fraction from a signed edge in [-1, 1].

    Uses fractional Kelly (¼ by default) and a hard cap, because noisy edge
    estimates make full Kelly ruinous — under-betting is recoverable,
    over-betting is not.
    """
    raw = max(-1.0, min(1.0, float(edge)))
    return float(np.clip(raw * fraction, -cap, cap))


class MetaLabelGate:
    """Secondary sizing model: confidence -> size in [0, 1] via an ECDF.

    Fit on a history of realised signal confidences; ``size`` returns the
    empirical percentile of a new confidence (so sizing reflects how strong this
    signal is *relative to history*), zeroed below ``min_confidence`` to filter
    false positives.
    """

    def __init__(self, min_confidence: float = 0.55) -> None:
        self.min_confidence = min_confidence
        self._sorted: list[float] = []

    def fit(self, confidences) -> "MetaLabelGate":
        self._sorted = sorted(float(c) for c in confidences)
        return self

    def size(self, confidence: float) -> float:
        c = float(confidence)
        if c < self.min_confidence:
            return 0.0
        if not self._sorted:
            # No history yet: fall back to the raw confidence.
            return max(0.0, min(1.0, c))
        rank = bisect_right(self._sorted, c)
        return rank / len(self._sorted)


@dataclass(frozen=True)
class EnsembleDecision:
    direction: int  # +1 long, -1 short, 0 flat
    size: float  # in [0, 1]
    combined_signal: float  # risk-parity blend in [-1, 1]
    confidence: float  # |combined_signal|
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "direction": self.direction,
            "size": round(self.size, 4),
            "combined_signal": round(self.combined_signal, 4),
            "confidence": round(self.confidence, 4),
            "reasons": self.reasons,
        }


@dataclass
class EnsembleStrategy:
    """Combine primary directional signals into one sized decision."""

    gate: MetaLabelGate = field(default_factory=MetaLabelGate)
    kelly_fraction: float = 0.25
    kelly_cap: float = 0.5
    target_volatility: float = 0.02  # per-period vol target for sizing overlay
    max_size: float = 1.0

    def decide(
        self,
        signals,
        vols,
        *,
        realized_vol: float | None = None,
        pm_price: float | None = None,
        is_buy_yes: bool | None = None,
    ) -> EnsembleDecision:
        combined = risk_parity_combine(signals, vols)
        direction = 1 if combined > 0 else -1 if combined < 0 else 0
        confidence = abs(combined)
        reasons: list[str] = [f"risk-parity blend={combined:+.3f}"]

        if direction == 0:
            return EnsembleDecision(0, 0.0, combined, confidence, ["flat: no net signal"])

        # 1) Meta-label sizing (confidence -> base size, filters weak signals).
        base_size = self.gate.size(confidence)
        if base_size <= 0:
            return EnsembleDecision(direction, 0.0, combined, confidence, ["meta-gate filtered (low confidence)"])
        reasons.append(f"meta-size={base_size:.2f}")

        # 2) Fractional-Kelly cap on the signed edge.
        kelly = abs(fractional_kelly(combined, fraction=self.kelly_fraction, cap=self.kelly_cap))
        size = base_size * (kelly / self.kelly_cap)  # normalise so cap==full
        reasons.append(f"kelly={kelly:.3f}")

        # 3) Volatility targeting overlay.
        if realized_vol is not None and realized_vol > 0:
            vol_scale = min(1.0, self.target_volatility / realized_vol)
            size *= vol_scale
            reasons.append(f"vol-scale={vol_scale:.2f}")

        # 4) Favorite-longshot discipline for prediction-market YES buys.
        if pm_price is not None and is_buy_yes is not None:
            fl_scale = longshot_size_scale(pm_price, is_buy_yes=is_buy_yes)
            size *= fl_scale
            if fl_scale < 1.0:
                reasons.append(f"longshot-scale={fl_scale:.2f}")

        size = float(max(0.0, min(self.max_size, size)))
        return EnsembleDecision(direction, size, combined, confidence, reasons)


__all__ = [
    "EnsembleDecision",
    "EnsembleStrategy",
    "MetaLabelGate",
    "fractional_kelly",
    "inverse_volatility_weights",
    "risk_parity_combine",
]
