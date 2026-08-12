"""Opt-in forecasting lab.

Forecasts are research artifacts, never trade permission.  The package keeps
heavy model imports lazy so the default PolyBob API remains lightweight.
"""

from .contracts import (
    AssetClass,
    BarInterval,
    CanonicalBar,
    CanonicalBarFrame,
    ForecastArtifact,
    ForecastPoint,
    ForecastStatus,
)

__all__ = [
    "AssetClass",
    "BarInterval",
    "CanonicalBar",
    "CanonicalBarFrame",
    "ForecastArtifact",
    "ForecastPoint",
    "ForecastStatus",
]
