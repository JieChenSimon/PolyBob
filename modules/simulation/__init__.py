"""Paper-trading simulation service package."""

from modules.simulation.service import (
    InvalidRunTransitionError,
    SimulationService,
    UnknownRunError,
    downsample_equity_curve,
)
from modules.simulation.sources import SignalSource, SimSignal

__all__ = [
    "InvalidRunTransitionError",
    "SignalSource",
    "SimSignal",
    "SimulationService",
    "UnknownRunError",
    "downsample_equity_curve",
]
