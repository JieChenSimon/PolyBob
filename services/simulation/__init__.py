"""Paper-trading simulation service package."""

from services.simulation.service import (
    InvalidRunTransitionError,
    SimulationService,
    UnknownRunError,
    downsample_equity_curve,
)
from services.simulation.sources import SignalSource, SimSignal

__all__ = [
    "InvalidRunTransitionError",
    "SignalSource",
    "SimSignal",
    "SimulationService",
    "UnknownRunError",
    "downsample_equity_curve",
]
