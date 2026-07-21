"""Point-in-time data and look-ahead (leakage) protection.

Look-ahead bias — using information in a backtest that would not have been
available at decision time — is the single most damaging error in quantitative
research: it produces results that are "fundamentally fictitious" and evaporate
in live trading. Vectorized backtests are especially prone to it because a
single line can silently reference future rows.

This module gives three defences that make leakage *detectable and structurally
avoidable* rather than a matter of programmer discipline:

- :class:`PointInTimeSeries` — stores every observation with both its event
  time and the time it actually became available (``available_at``), so a
  reporting/vendor lag is modelled explicitly. ``as_of(t)`` returns only what a
  trader could have known at ``t``.
- :func:`lag_signals` — enforces the "decide on the last *closed* bar" rule by
  shifting a signal series forward one step.
- :func:`assert_no_lookahead` / :func:`find_lookahead` — a harness that proves a
  signal function is causal by checking that the signal at bar ``k`` is
  identical whether or not future bars are present. This is the definitive test
  that catches the subtle vectorized leaks discipline alone misses.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Generic, Sequence, TypeVar

T = TypeVar("T")


class LookaheadError(AssertionError):
    """Raised when a signal function is shown to use future information."""


@dataclass(frozen=True)
class Observation(Generic[T]):
    event_time: datetime
    available_at: datetime
    value: T

    def __post_init__(self) -> None:
        if self.available_at < self.event_time:
            raise ValueError(
                "available_at cannot precede event_time "
                f"({self.available_at} < {self.event_time})"
            )


class PointInTimeSeries(Generic[T]):
    """A time series that knows *when each value became available*.

    Querying with :meth:`as_of` returns only the observations a decision-maker
    could have seen at that instant, so downstream code cannot accidentally read
    a value published in the future (the classic "earnings known before release"
    leak).
    """

    def __init__(self, observations: Sequence[Observation[T]] | None = None) -> None:
        self._obs: list[Observation[T]] = []
        for obs in observations or []:
            self.add(obs)

    def add(self, observation: Observation[T]) -> None:
        self._obs.append(observation)
        # Keep ordered by availability for efficient as_of queries.
        self._obs.sort(key=lambda o: (o.available_at, o.event_time))

    def add_value(self, event_time: datetime, value: T, *, available_at: datetime | None = None) -> None:
        self.add(Observation(event_time, available_at or event_time, value))

    def as_of(self, when: datetime) -> list[Observation[T]]:
        """Observations available at or before ``when`` (event-time ordered)."""
        available = [o for o in self._obs if o.available_at <= when]
        available.sort(key=lambda o: o.event_time)
        return available

    def latest_as_of(self, when: datetime) -> Observation[T] | None:
        available = self.as_of(when)
        return available[-1] if available else None

    def values_as_of(self, when: datetime) -> list[T]:
        return [o.value for o in self.as_of(when)]

    def __len__(self) -> int:
        return len(self._obs)


def lag_signals(signals: Sequence[T], *, fill: T | None = None) -> list[T]:
    """Shift a signal series forward one step ("act on the last closed bar").

    ``signals[i]`` becomes the decision applied at bar ``i+1``; the first bar
    gets ``fill`` (default ``None``) because no prior closed bar exists.
    """
    if not signals:
        return []
    return [fill, *list(signals[:-1])]


def find_lookahead(
    signal_fn: Callable[[Sequence[Any]], Sequence[T]],
    history: Sequence[Any],
    *,
    min_prefix: int = 1,
    check_indices: Sequence[int] | None = None,
    equal: Callable[[T, T], bool] | None = None,
) -> list[int]:
    """Return the bar indices at which ``signal_fn`` leaks future information.

    ``signal_fn`` maps a sequence of bars to a sequence of signals aligned to
    those bars. A *causal* function satisfies, for every ``k``::

        signal_fn(history[: k + 1])[k] == signal_fn(history)[k]

    i.e. bar ``k``'s signal must not change when future bars are revealed. Any
    index where it *does* change is returned as evidence of look-ahead.
    """
    n = len(history)
    if n == 0:
        return []
    full = list(signal_fn(history))
    if len(full) != n:
        raise ValueError(
            f"signal_fn returned {len(full)} signals for {n} bars; it must align 1:1"
        )
    eq = equal or _default_equal
    indices = check_indices if check_indices is not None else range(max(min_prefix - 1, 0), n)
    leaks: list[int] = []
    for k in indices:
        if k < 0 or k >= n:
            continue
        prefix_signals = list(signal_fn(history[: k + 1]))
        if len(prefix_signals) != k + 1:
            raise ValueError(
                f"signal_fn returned {len(prefix_signals)} signals for a {k + 1}-bar prefix"
            )
        if not eq(prefix_signals[k], full[k]):
            leaks.append(k)
    return leaks


def assert_no_lookahead(
    signal_fn: Callable[[Sequence[Any]], Sequence[T]],
    history: Sequence[Any],
    *,
    min_prefix: int = 1,
    check_indices: Sequence[int] | None = None,
    equal: Callable[[T, T], bool] | None = None,
) -> None:
    """Raise :class:`LookaheadError` if ``signal_fn`` is not causal.

    Wrap a strategy's signal computation in a unit test with this to make
    look-ahead a build-breaking failure instead of a live-trading surprise.
    """
    leaks = find_lookahead(
        signal_fn,
        history,
        min_prefix=min_prefix,
        check_indices=check_indices,
        equal=equal,
    )
    if leaks:
        preview = leaks[:10]
        raise LookaheadError(
            f"signal_fn uses future data at {len(leaks)} bar(s); first offending "
            f"indices: {preview}. A causal signal must not change bar k when later "
            "bars are appended."
        )


def _default_equal(a: Any, b: Any) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        if a != a and b != b:  # both NaN
            return True
        return abs(a - b) <= 1e-9 + 1e-9 * max(abs(a), abs(b))
    return a == b


__all__ = [
    "LookaheadError",
    "Observation",
    "PointInTimeSeries",
    "assert_no_lookahead",
    "find_lookahead",
    "lag_signals",
]
