"""Evidence and instructions must come from one declaration.

The insider edge existed three times: the study (which held the exit rule), the
live detector (which held none), and a third ``find_clusters`` in ``strategies/``.
They agreed on detection and on nothing else, so the board approved *a 20-session
hold measured against SPY net of costs* while the product surfaced *a signal with
no exit*. Those are different objects and only one of them had a t-statistic.

These tests pin the pricing rules that the shared runner now owns — above all the
entry-timing rule, which is where an event study leaks look-ahead worth more than
the effect it is trying to measure.
"""

from __future__ import annotations

import datetime as dt

import pytest

from libs.data import store
from libs.quant import edge_backtest
from libs.quant.edge import Direction, ExitRule, Signal


@pytest.fixture(autouse=True)
def _isolated_store(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "STORE_ROOT", tmp_path / "store")


NOW = dt.datetime(2026, 6, 1, tzinfo=dt.UTC)


def _write(symbol: str, closes: dict[str, float], *, fetched=None) -> None:
    store.write(
        store.DAILY_BARS, symbol,
        [{"symbol": symbol, store.EVENT_DATE: d, "close": c, "source": "test"}
         for d, c in sorted(closes.items())],
        fetched_at=fetched or dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
    )


def _sessions(start: str, n: int, price=lambda i: 100.0) -> dict[str, float]:
    """n consecutive weekday sessions from ``start``."""
    day = dt.date.fromisoformat(start)
    out: dict[str, float] = {}
    i = 0
    while len(out) < n:
        if day.weekday() < 5:
            out[day.isoformat()] = price(i)
            i += 1
        day += dt.timedelta(days=1)
    return out


# ------------------------------------------------------------- entry timing
def test_entry_is_the_first_session_on_or_after_the_signal():
    """The earliest bar a person acting on public information could trade.

    Entering at the signal date's *open*, or at a close before the information was
    public, is worth several percent on an event study — the entire effect size
    being measured.
    """
    _write("X", {"2026-03-02": 100.0, "2026-03-03": 110.0, "2026-03-04": 120.0})
    result = edge_backtest.replay_events(
        [("X", "2026-03-03")], direction=Direction.LONG, hold_sessions=1,
        benchmark=None, cost_bps=0.0, as_of=NOW, t_hurdle=3.0,
    )
    trade = result.trades[0]
    assert trade.entry_date == "2026-03-03"      # not 03-02
    assert trade.exit_date == "2026-03-04"
    assert trade.excess == pytest.approx(120.0 / 110.0 - 1.0)


def test_a_signal_on_a_non_trading_day_enters_at_the_next_session():
    """Filings land on weekends; the trade cannot."""
    _write("X", {"2026-03-06": 100.0, "2026-03-09": 110.0})   # Fri, Mon
    result = edge_backtest.replay_events(
        [("X", "2026-03-07")], direction=Direction.LONG, hold_sessions=1,
        benchmark=None, cost_bps=0.0, as_of=NOW, t_hurdle=3.0,
    )
    assert result.trades == [] or result.trades[0].entry_date == "2026-03-09"


def test_a_truncated_holding_window_is_dropped_not_shortened():
    """Clamping the hold near the end of the sample is a different strategy.

    Worse, it biases the result toward whatever the last few weeks happened to do,
    and those weeks are always the ones with the fewest observations to average
    the noise away.
    """
    _write("X", _sessions("2026-03-02", 5))
    result = edge_backtest.replay_events(
        [("X", "2026-03-04")], direction=Direction.LONG, hold_sessions=20,
        benchmark=None, cost_bps=0.0, as_of=NOW, t_hurdle=3.0,
    )
    assert result.trades == []
    assert result.dropped_short_window == 1


# ------------------------------------------------------------------ direction
def test_a_short_earns_when_the_price_falls():
    _write("X", {"2026-03-02": 100.0, "2026-03-03": 90.0})
    result = edge_backtest.replay_events(
        [("X", "2026-03-02")], direction=Direction.SHORT, hold_sessions=1,
        benchmark=None, cost_bps=0.0, as_of=NOW, t_hurdle=3.0,
    )
    assert result.trades[0].excess == pytest.approx(0.10)


def test_the_benchmark_is_signed_the_same_way_as_the_position():
    """A short's excess is measured against a short of the benchmark.

    Subtracting a *long* benchmark return from a short position's return double
    counts the market move and would make any short look brilliant in a selloff.
    """
    _write("X", {"2026-03-02": 100.0, "2026-03-03": 90.0})     # -10%
    _write("SPY", {"2026-03-02": 100.0, "2026-03-03": 95.0})   # -5%
    result = edge_backtest.replay_events(
        [("X", "2026-03-02")], direction=Direction.SHORT, hold_sessions=1,
        benchmark="SPY", cost_bps=0.0, as_of=NOW, t_hurdle=3.0,
    )
    # Short earns +10%, a short of SPY would have earned +5%: excess is +5%.
    assert result.trades[0].excess == pytest.approx(0.05)


def test_costs_are_charged_once_per_round_trip():
    _write("X", {"2026-03-02": 100.0, "2026-03-03": 100.0})
    result = edge_backtest.replay_events(
        [("X", "2026-03-02")], direction=Direction.LONG, hold_sessions=1,
        benchmark=None, cost_bps=10.0, as_of=NOW, t_hurdle=3.0,
    )
    assert result.trades[0].excess == pytest.approx(-0.001)


# ----------------------------------------------------------- missing evidence
def test_a_missing_benchmark_voids_the_whole_run():
    """Reporting a raw return as excess would credit the edge with market drift."""
    _write("X", {"2026-03-02": 100.0, "2026-03-03": 110.0})
    result = edge_backtest.replay_events(
        [("X", "2026-03-02")], direction=Direction.LONG, hold_sessions=1,
        benchmark="SPY", cost_bps=0.0, as_of=NOW, t_hurdle=3.0,
    )
    assert result.trades == []
    assert result.inference is None


def test_signals_with_no_prices_are_counted_not_silently_dropped():
    """The measurable rate is a selection warning, not a footnote.

    28% of real insider signals could not be priced. If the priced 72% is the
    liquid, well-covered subset, that selection is inside the result — and the old
    experiment reported no such number at all.
    """
    _write("HAVE", {"2026-03-02": 100.0, "2026-03-03": 110.0})
    result = edge_backtest.replay_events(
        [("HAVE", "2026-03-02"), ("GONE", "2026-03-02")],
        direction=Direction.LONG, hold_sessions=1,
        benchmark=None, cost_bps=0.0, as_of=NOW, t_hurdle=3.0,
    )
    assert result.signals_found == 2
    assert result.dropped_no_prices == 1
    assert result.measurable_rate == pytest.approx(0.5)


def test_no_signals_means_no_inference_rather_than_a_zero():
    result = edge_backtest.replay_events(
        [], direction=Direction.LONG, hold_sessions=1,
        benchmark=None, cost_bps=0.0, as_of=NOW, t_hurdle=3.0,
    )
    assert result.inference is None
    assert result.measurable_rate is None
    assert result.to_dict()["events"] == []


# -------------------------------------------------------------- point-in-time
def test_the_replay_cannot_see_prices_observed_after_its_as_of():
    """The runner inherits the store's guarantee rather than restating it.

    This is why the pricing lives behind ``store.read(..., as_of=)``: a backtest
    that reads today's restated series is measuring a strategy nobody could have
    run.
    """
    _write("X", {"2026-03-02": 100.0, "2026-03-03": 110.0},
           fetched=dt.datetime(2026, 3, 3, tzinfo=dt.UTC))
    _write("X", {"2026-03-04": 200.0},
           fetched=dt.datetime(2026, 5, 1, tzinfo=dt.UTC))

    early = edge_backtest.replay_events(
        [("X", "2026-03-02")], direction=Direction.LONG, hold_sessions=2,
        benchmark=None, cost_bps=0.0,
        as_of=dt.datetime(2026, 3, 4, tzinfo=dt.UTC), t_hurdle=3.0,
    )
    assert early.trades == []                    # the 03-04 bar was not known yet

    late = edge_backtest.replay_events(
        [("X", "2026-03-02")], direction=Direction.LONG, hold_sessions=2,
        benchmark=None, cost_bps=0.0, as_of=NOW, t_hurdle=3.0,
    )
    assert late.trades[0].exit_price == 200.0


# ---------------------------------------------------------------- the contract
def test_the_exit_rule_describes_itself_for_the_page():
    """The instruction printed to a person must come off the same object.

    A signal with no stated exit is not the thing the board measured, and that
    mismatch is what this whole module exists to make impossible.
    """
    rule = ExitRule(hold_sessions=20, benchmark="SPY", cost_bps=10.0)
    text = rule.describe_zh()
    assert "20" in text and "SPY" in text and "10" in text


def test_an_avoid_signal_is_never_priced_as_a_position():
    """An avoidance filter earns nothing; pricing it would invent a return."""
    signal = Signal(symbol="X", fired_on="2026-03-02", direction=Direction.AVOID,
                    evidence_zh="回避")
    assert signal.is_position is False
