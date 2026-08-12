"""Replay an :class:`~libs.quant.edge.Edge` over history to produce its evidence.

This is the other half of the common core. The experiment scripts each grew their
own ``forward_return`` — three near-identical functions, each with its own idea of
where entry happens and whether the benchmark is aligned — and the live scan grew
none, so it surfaced signals with no exit. Here the exit comes off the edge's own
:class:`~libs.quant.edge.ExitRule`, which means the number the board sees and the
instruction the page prints are derived from one declaration.

Entry timing is fixed here rather than per-experiment, because it is the single
easiest place to leak look-ahead: **enter at the first close on or after the
signal date**. Not the close of the signal date itself unless the information was
public before that close, and never the open of the signal date. Getting this
wrong is worth a few percent a year on an event study, which is the entire effect
size being measured.

All reads are point-in-time. The runner takes an ``as_of`` and hands it to both
:meth:`Edge.detect` and the price reads, so the evidence describes what was
knowable then.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import numpy as np

from libs.data import store
from libs.quant.clustered_inference import ClusteredResult, analyse
from libs.quant.edge import Direction, Edge, Signal

# Below this a trailing daily volatility is a data artefact rather than a quiet stock:
# a halted name, a stale feed, a fund NAV. Horizon-independent by construction.
MIN_DAILY_VOL = 0.0005


@dataclass(frozen=True)
class Trade:
    """One replayed round trip, priced exactly as the edge declares."""

    symbol: str
    signal_date: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    gross_return: float           # signed by direction, before benchmark and cost
    benchmark_return: float | None
    excess: float                 # what the statistics are computed on
    # Position weight applied to reach ``excess``. 1.0 under equal weighting. Exposed
    # because anything reasoning in *raw return* units — a power study injecting a known
    # economic edge, say — has to undo the scaling, and guessing at it silently changes
    # what is being measured.
    risk_weight: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "date": self.signal_date,
            "entry_date": self.entry_date,
            "exit_date": self.exit_date,
            "excess": round(self.excess, 6),
        }


@dataclass
class BacktestResult:
    """Evidence for one edge, plus the accounting of what could not be measured."""

    edge_id: str
    trades: list[Trade] = field(default_factory=list)
    signals_found: int = 0
    dropped_no_prices: int = 0
    dropped_short_window: int = 0
    dropped_no_benchmark: int = 0
    dropped_no_carry: int = 0
    dropped_no_risk_estimate: int = 0
    inference: ClusteredResult | None = None

    @property
    def measurable_rate(self) -> float | None:
        """Share of signals that became a priced trade.

        A low rate is a warning, not a detail: if half the signals cannot be
        priced, the surviving half may be the liquid, well-covered half, and that
        is a selection effect sitting inside the result.
        """
        if not self.signals_found:
            return None
        return len(self.trades) / self.signals_found

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "strategy": self.edge_id,
            "signals_found": self.signals_found,
            "dropped": {
                "no_prices": self.dropped_no_prices,
                "window_too_short": self.dropped_short_window,
                "no_benchmark": self.dropped_no_benchmark,
                "no_carry": self.dropped_no_carry,
                "no_risk_estimate": self.dropped_no_risk_estimate,
            },
            "measurable_rate": (
                None if self.measurable_rate is None else round(self.measurable_rate, 4)
            ),
        }
        if self.inference is not None:
            payload.update(self.inference.to_dict())
        payload["events"] = [t.to_dict() for t in sorted(self.trades, key=lambda t: t.signal_date)]
        return payload


def _series(symbol: str, as_of: dt.datetime) -> tuple[list[str], list[float]] | None:
    frame = store.read(store.DAILY_BARS, symbol, as_of=as_of)
    if len(frame) == 0:
        return None
    dates = [str(d) for d in frame[store.EVENT_DATE].tolist()]
    closes = [float(c) for c in frame["close"].tolist()]
    return dates, closes


def _series_bulk(
    symbols: Sequence[str], as_of: dt.datetime
) -> dict[str, tuple[list[str], list[float]]]:
    """Every symbol's closes in one query rather than one query each.

    Measured on the real store: 60 symbols read individually cost 0.29s, the same 60
    read together cost 0.02s — 18x, because each per-symbol call re-plans the query
    and re-opens the parquet files. It matters here because a replay touches hundreds
    of symbols, and it matters in the live scan for the same reason.
    """
    if not symbols:
        return {}
    frame = store.read(store.DAILY_BARS, list(dict.fromkeys(symbols)), as_of=as_of)
    out: dict[str, tuple[list[str], list[float]]] = {}
    if len(frame) == 0:
        return out
    # The frame arrives ordered by (symbol, event_date), so a single pass groups it.
    for symbol, group in frame.groupby("symbol", sort=False):
        out[str(symbol)] = (
            [str(d) for d in group[store.EVENT_DATE].tolist()],
            [float(c) for c in group["close"].tolist()],
        )
    return out


def _forward(
    dates: Sequence[str], closes: Sequence[float], signal_date: str, hold: int
) -> tuple[int, int] | None:
    """Indices of (entry, exit), or ``None`` when the window does not fit.

    Entry is the first session **on or after** the signal date — the earliest bar
    a person acting on public information could have traded. Exit is ``hold``
    sessions later. Returning ``None`` rather than clamping matters: a truncated
    hold is a different strategy, and silently shortening it near the end of the
    sample biases the result toward whatever the last few weeks did.
    """
    entry = next((i for i, d in enumerate(dates) if d >= signal_date), None)
    if entry is None:
        return None
    exit_i = entry + hold
    if exit_i >= len(closes) or closes[entry] <= 0:
        return None
    return entry, exit_i


def run(
    edge: Edge,
    *,
    as_of: dt.datetime,
    start: dt.date | str | None = None,
    end: dt.date | str | None = None,
    t_hurdle: float,
) -> BacktestResult:
    """Replay ``edge`` and return its evidence.

    ``t_hurdle`` is passed in rather than computed here: it comes from the
    hypothesis registry's trial count, and an edge must not be able to choose the
    bar it is judged against.
    """
    result = BacktestResult(edge_id=edge.id)
    rule = edge.exit_rule
    symbols = list(edge.universe(as_of))

    bench: tuple[list[str], list[float]] | None = None
    if rule.benchmark:
        bench = _series(rule.benchmark, as_of)
        if bench is None:
            # No benchmark means excess return is not computable. The alternative —
            # reporting a raw return as if it were excess — would credit the edge
            # with the whole market's drift.
            result.dropped_no_benchmark = -1
            return result

    sign = -1.0 if edge.direction is Direction.SHORT else 1.0
    cost = rule.cost_bps / 1e4

    for symbol in symbols:
        signal = edge.detect(symbol, as_of)
        if signal is None:
            continue
        result.signals_found += 1
        if not signal.is_position:
            continue

        prices = _series(symbol, as_of)
        if prices is None:
            result.dropped_no_prices += 1
            continue
        dates, closes = prices
        window = _forward(dates, closes, signal.fired_on, rule.hold_sessions)
        if window is None:
            result.dropped_short_window += 1
            continue
        entry_i, exit_i = window
        gross = sign * (closes[exit_i] / closes[entry_i] - 1.0)

        benchmark_return: float | None = None
        if bench is not None:
            b_window = _forward(bench[0], bench[1], signal.fired_on, rule.hold_sessions)
            if b_window is None:
                result.dropped_no_benchmark += 1
                continue
            b_entry, b_exit = b_window
            benchmark_return = sign * (bench[1][b_exit] / bench[1][b_entry] - 1.0)

        excess = gross - (benchmark_return or 0.0) - cost
        result.trades.append(Trade(
            symbol=symbol, signal_date=signal.fired_on,
            entry_date=dates[entry_i], exit_date=dates[exit_i],
            entry_price=closes[entry_i], exit_price=closes[exit_i],
            gross_return=gross, benchmark_return=benchmark_return, excess=excess,
        ))

    if result.trades:
        result.inference = analyse(
            [t.excess for t in result.trades],
            [t.signal_date for t in result.trades],
            t_hurdle=t_hurdle, hold_days=rule.hold_sessions,
        )
    return result


def replay_events(
    events: Sequence[tuple[str, str]],
    *,
    direction: Direction,
    hold_sessions: int,
    benchmark: str | None,
    cost_bps: float,
    as_of: dt.datetime,
    t_hurdle: float,
    edge_id: str = "replay",
    carry: Callable[[str, str, Sequence[str], int], float | None] | None = None,
    neutralise_universe: Sequence[str] | None = None,
    risk_scale_window: int | None = None,
    risk_target: float = 0.20,
) -> BacktestResult:
    """Price a list of ``(symbol, signal_date)`` events under one exit rule.

    The bridge for edges whose detection is a bulk operation over a whole filing
    dataset rather than a per-symbol question — the insider study finds its 1,141
    clusters in one pass over SEC data, and asking it symbol-by-symbol would mean
    re-parsing three quarters of filings per ticker. The *pricing* is identical to
    :func:`run`, which is the part that has to agree.

    ``carry`` adds a holding cost or income that is not in the price: funding for a
    perpetual short, borrow for an equity short, dividends for a long. It is called
    with ``(symbol, signal_date, session_dates, entry_index)`` and must return the
    total over the holding window, or ``None`` when it cannot be measured.

    ``None`` **drops the event** rather than treating the carry as zero. That is not
    fastidiousness: the altcoin edge is a perp short selected precisely on crowded
    longs, which is the state where longs *pay* shorts. Assuming zero funding there
    does not add noise, it biases the one leg being traded — and it biases it against
    the edge, which is the direction that looks conservative and is actually just
    wrong.

    ``neutralise_universe`` replaces the index benchmark with the equal-weighted mean
    forward return of that universe on the same date — the cross-sectional control.

    The reason is a priori, and that distinction is the point. Insider cluster buys
    concentrate in small caps while SPY is large-cap, so subtracting SPY leaves a
    size-factor exposure inside what gets called alpha. Demeaning against the population
    the events are drawn from removes whatever is common to it, by construction, without
    estimating a beta.

    Four benchmarks were measured before this was chosen — SPY, QQQ, cross-sectional and
    a 50/50 blend — and all four are registered as trials, because a search over
    benchmarks is a search. The blend produced the highest t-statistic and was **not**
    chosen: it has no prior justification, and picking the winner of a search is the data
    snooping this project exists to avoid. The cross-sectional control in fact gives a
    *lower* t than SPY (3.58 against 3.67), because part of the SPY-excess was small-cap
    beta rather than alpha; the honest effect estimate is the smaller one. What improves
    is future power — cluster SD 3.87% -> 3.37%, so the minimum detectable effect falls
    from 5.40% to 4.70%.

    ``risk_scale_window`` sizes each event inversely to the instrument's volatility over
    that many sessions *before* the signal, expressed at ``risk_target``. This is a
    different **implementation** of the same edge, not a different measurement of it, and
    it is registered as its own trial.

    The prior argument, again made before looking: equal-weighting hands the P&L to
    whichever names happen to be most volatile. A cluster of thirty events where one is a
    60%-vol microcap and the rest are 20%-vol mid caps is, in practice, mostly a bet on
    the microcap. Equal *risk* contribution is what a desk does, and it is the sizing the
    portfolio layer will apply anyway — so measuring the equal-weighted version measures a
    strategy nobody would run.

    Measured, it improves the quality of the estimate rather than its size: median +0.41%
    -> +0.80%, mean/median skew 9.8 -> 4.2, minimum detectable effect 4.71% -> 3.95%. The
    mean *falls* (4.02% -> 3.39%) because the volatile names that were carrying it now
    carry proportionally less, which is the honest direction. Volatility is estimated
    strictly from bars before the signal, so it is available at decision time.
    """
    edge_result = BacktestResult(edge_id=edge_id)
    sign = -1.0 if direction is Direction.SHORT else 1.0
    cost = cost_bps / 1e4

    bench: tuple[list[str], list[float]] | None = None
    if benchmark:
        bench = _series(benchmark, as_of)
        if bench is None:
            edge_result.dropped_no_benchmark = -1
            return edge_result

    # One bulk read up front, not one per event.
    prices = _series_bulk([symbol for symbol, _ in events], as_of)

    # The cross-sectional control, cached per date. A minimum breadth is required: the
    # "average" of six stocks is not a market, and using one would swap a benchmark for
    # noise.
    control: dict[str, float | None] = {}
    control_series = (
        _series_bulk(list(neutralise_universe), as_of) if neutralise_universe else {}
    )

    def _risk_weight(symbol: str, dates_: Sequence[str], entry_index: int) -> float | None:
        """Target vol over the instrument's own trailing vol, or ``None`` if unmeasurable.

        Uses only bars strictly *before* the entry, so the weight is knowable at decision
        time. An event without enough pre-history is dropped rather than assigned a
        guessed volatility — a fabricated risk estimate is worse than a missing event,
        because it silently changes the weight of everything else.
        """
        if not risk_scale_window:
            return 1.0
        series = prices.get(symbol)
        if series is None or entry_index < risk_scale_window + 1:
            return None
        closes_ = np.asarray(series[1][entry_index - risk_scale_window:entry_index], float)
        if len(closes_) < risk_scale_window or (closes_ <= 0).any():
            return None
        log_returns = np.diff(np.log(closes_))
        sd = float(log_returns.std(ddof=1))
        # The floor is on *daily* volatility, not on the horizon figure. A near-zero
        # trailing vol produces an enormous weight from what is almost always a data
        # artefact — a halted name, a stale feed, a fund NAV — so it is refused. Putting
        # the floor on the horizon vol instead was a bug: ``sd * sqrt(hold)`` is small
        # whenever the hold is short, so a one-session edge would have had every ordinary
        # instrument rejected as "too quiet". A stock moving under 5bps a day is degenerate
        # at any horizon; one moving 2% over a single session is not.
        if sd < MIN_DAILY_VOL:
            return None
        horizon_vol = sd * np.sqrt(hold_sessions)
        return risk_target / horizon_vol

    def _cross_sectional(date: str) -> float | None:
        if not control_series:
            return None
        if date not in control:
            values = []
            for dates_, closes_ in control_series.values():
                window = _forward(dates_, closes_, date, hold_sessions)
                if window is not None:
                    values.append(closes_[window[1]] / closes_[window[0]] - 1.0)
            control[date] = float(np.mean(values)) if len(values) >= 30 else None
        return control[date]

    for symbol, signal_date in events:
        edge_result.signals_found += 1
        series = prices.get(symbol)
        if series is None:
            edge_result.dropped_no_prices += 1
            continue
        dates, closes = series
        window = _forward(dates, closes, signal_date, hold_sessions)
        if window is None:
            edge_result.dropped_short_window += 1
            continue
        entry_i, exit_i = window
        gross = sign * (closes[exit_i] / closes[entry_i] - 1.0)

        benchmark_return: float | None = None
        if neutralise_universe:
            raw_control = _cross_sectional(signal_date)
            if raw_control is None:
                edge_result.dropped_no_benchmark += 1
                continue
            benchmark_return = sign * raw_control
        elif bench is not None:
            b_window = _forward(bench[0], bench[1], signal_date, hold_sessions)
            if b_window is None:
                edge_result.dropped_no_benchmark += 1
                continue
            benchmark_return = sign * (bench[1][b_window[1]] / bench[1][b_window[0]] - 1.0)

        carry_return = 0.0
        if carry is not None:
            measured = carry(symbol, signal_date, dates, entry_i)
            if measured is None:
                edge_result.dropped_no_carry += 1
                continue
            carry_return = measured

        weight = _risk_weight(symbol, dates, entry_i)
        if weight is None:
            edge_result.dropped_no_risk_estimate += 1
            continue

        edge_result.trades.append(Trade(
            symbol=symbol, signal_date=signal_date,
            entry_date=dates[entry_i], exit_date=dates[exit_i],
            entry_price=closes[entry_i], exit_price=closes[exit_i],
            gross_return=gross, benchmark_return=benchmark_return,
            excess=(gross - (benchmark_return or 0.0) + carry_return - cost) * weight,
            risk_weight=weight,
        ))

    if edge_result.trades:
        edge_result.inference = analyse(
            [t.excess for t in edge_result.trades],
            [t.signal_date for t in edge_result.trades],
            t_hurdle=t_hurdle, hold_days=hold_sessions,
        )
    return edge_result


__all__ = ["BacktestResult", "Trade", "replay_events", "run"]
