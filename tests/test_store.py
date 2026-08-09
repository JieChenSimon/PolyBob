"""The store's one job: make look-ahead unreachable, not merely detectable.

The defect that motivated this module was measured, not theorised. Re-running the
insider experiment on "the same" cache produced n=753 one day and n=667 the next,
because ``data/market_cache/`` was 613 overwritable JSON files with no observation
time. These tests pin the properties that make that impossible now.

``libs/quant/pit.py`` already had look-ahead helpers and they worked — but nine
test files called them and zero production modules did. A guarantee that lives in
tests is a convention. The point of putting the filter inside :func:`store.read`
is that a caller cannot opt out of it.
"""

from __future__ import annotations

import datetime as dt

import pytest

from libs.data import store


@pytest.fixture(autouse=True)
def _isolated_store(monkeypatch, tmp_path):
    """Never touch the real store: these tests write."""
    monkeypatch.setattr(store, "STORE_ROOT", tmp_path / "store")
    return tmp_path


def _t(day: str, hour: int = 12) -> dt.datetime:
    return dt.datetime.fromisoformat(day).replace(hour=hour, tzinfo=dt.UTC)


def _bar(date: str, close: float) -> dict:
    return {"symbol": "AAPL", store.EVENT_DATE: date, "close": close, "source": "test"}


# ------------------------------------------------------ the temporal guarantee
def test_as_of_hides_rows_observed_later():
    """The whole reason the store exists.

    A backtest reading with ``as_of`` must see the data as it stood then. If a row
    fetched afterwards leaks in, every result computed on top is contaminated with
    knowledge that did not exist at the time.
    """
    store.write(store.DAILY_BARS, "AAPL", [_bar("2026-01-05", 100.0)],
                fetched_at=_t("2026-01-05"))
    store.write(store.DAILY_BARS, "AAPL", [_bar("2026-01-06", 101.0)],
                fetched_at=_t("2026-01-06"))

    early = store.read(store.DAILY_BARS, "AAPL", as_of=_t("2026-01-05", 23))
    assert list(early[store.EVENT_DATE]) == ["2026-01-05"]

    later = store.read(store.DAILY_BARS, "AAPL", as_of=_t("2026-01-07"))
    assert list(later[store.EVENT_DATE]) == ["2026-01-05", "2026-01-06"]


def test_a_restatement_does_not_rewrite_the_past():
    """Re-fetching appends; it never destroys the value you actually traded on.

    Providers restate history — splits, adjustments, corrections. The old cache
    overwrote in place, so a backtest silently used the *corrected* series while
    claiming to describe decisions made on the original one.
    """
    store.write(store.DAILY_BARS, "AAPL", [_bar("2026-01-05", 100.0)],
                fetched_at=_t("2026-01-05"))
    store.write(store.DAILY_BARS, "AAPL", [_bar("2026-01-05", 50.0)],   # a 2:1 split
                fetched_at=_t("2026-02-01"))

    before = store.read(store.DAILY_BARS, "AAPL", as_of=_t("2026-01-10"))
    after = store.read(store.DAILY_BARS, "AAPL", as_of=_t("2026-03-01"))
    assert float(before["close"].iloc[0]) == 100.0     # what we knew in January
    assert float(after["close"].iloc[0]) == 50.0       # what we know now


def test_restatements_are_queryable():
    """"How much of my sample was silently revised?" must have an answer."""
    store.write(store.DAILY_BARS, "AAPL", [_bar("2026-01-05", 100.0)],
                fetched_at=_t("2026-01-05"))
    store.write(store.DAILY_BARS, "AAPL", [_bar("2026-01-05", 50.0)],
                fetched_at=_t("2026-02-01"))
    store.write(store.DAILY_BARS, "AAPL", [_bar("2026-01-06", 101.0)],
                fetched_at=_t("2026-01-06"))

    revised = store.restatements(store.DAILY_BARS, "AAPL")
    assert list(revised[store.EVENT_DATE]) == ["2026-01-05"]
    assert int(revised["observations"].iloc[0]) == 2


def test_reading_twice_at_the_same_as_of_gives_the_same_rows():
    """The property the insider experiment lacked: a stable sample size.

    n=753 then n=667 with no code change is not a statistical subtlety, it is an
    unpinned input. Same ``as_of``, same answer — even after new data lands.
    """
    store.write(store.DAILY_BARS, "AAPL",
                [_bar("2026-01-05", 100.0), _bar("2026-01-06", 101.0)],
                fetched_at=_t("2026-01-06"))
    cut = _t("2026-01-07")
    first = store.read(store.DAILY_BARS, "AAPL", as_of=cut)

    store.write(store.DAILY_BARS, "AAPL", [_bar("2026-01-07", 99.0)],
                fetched_at=_t("2026-01-08"))
    second = store.read(store.DAILY_BARS, "AAPL", as_of=cut)

    assert len(first) == len(second) == 2
    assert list(first["close"]) == list(second["close"])


def test_no_as_of_means_everything_known_now():
    """A live scan legitimately knows the latest value; only research must pin."""
    store.write(store.DAILY_BARS, "AAPL", [_bar("2026-01-05", 100.0)],
                fetched_at=_t("2026-01-05"))
    store.write(store.DAILY_BARS, "AAPL", [_bar("2026-01-06", 101.0)],
                fetched_at=_t("2026-01-06"))
    assert len(store.read(store.DAILY_BARS, "AAPL")) == 2


# ---------------------------------------------------------------- write rules
def test_a_row_without_an_event_date_is_refused():
    """A row that cannot be placed in time cannot be read point-in-time.

    Accepting it would reintroduce exactly the table shape this store replaced, so
    the writer fails rather than storing something unreadable later.
    """
    with pytest.raises(store.StoreError, match="event_date"):
        store.write(store.DAILY_BARS, "AAPL", [{"symbol": "AAPL", "close": 1.0}])


def test_a_caller_cannot_forge_fetched_at_per_row():
    """``fetched_at`` describes the *fetch*, so one call carries one stamp.

    Letting individual rows claim their own observation time would let a caller
    backdate data it just received — look-ahead wearing the store's own clothes.
    """
    store.write(
        store.DAILY_BARS, "AAPL",
        [{**_bar("2026-01-05", 100.0), store.FETCHED_AT: _t("2020-01-01")}],
        fetched_at=_t("2026-01-05"),
    )
    assert len(store.read(store.DAILY_BARS, "AAPL", as_of=_t("2020-06-01"))) == 0
    assert len(store.read(store.DAILY_BARS, "AAPL", as_of=_t("2026-01-06"))) == 1


def test_an_undeclared_dataset_is_refused():
    """Datasets are declared in source, not conjured by a typo in a string."""
    with pytest.raises(KeyError, match="unknown dataset"):
        store.write("daily_barz", "AAPL", [_bar("2026-01-05", 1.0)])


def test_writing_nothing_is_not_an_error_and_creates_nothing():
    assert store.write(store.DAILY_BARS, "AAPL", []) == 0
    assert store.symbols(store.DAILY_BARS) == []


# --------------------------------------------------------------- read shapes
def test_missing_data_reads_as_empty_not_as_a_crash():
    """"No rows" and "no table" must be the same thing to a caller.

    Otherwise every call site grows a try/except, and a bare except around a data
    read is how a missing value becomes a zero.
    """
    frame = store.read(store.DAILY_BARS, "NOSUCH", as_of=_t("2026-01-05"))
    assert len(frame) == 0
    assert store.EVENT_DATE in frame.columns
    assert "close" in frame.columns


def test_date_range_filters_are_inclusive():
    store.write(store.DAILY_BARS, "AAPL",
                [_bar(f"2026-01-{d:02d}", 100.0 + d) for d in (5, 6, 7, 8)],
                fetched_at=_t("2026-01-09"))
    frame = store.read(store.DAILY_BARS, "AAPL", as_of=_t("2026-01-10"),
                       start="2026-01-06", end="2026-01-07")
    assert list(frame[store.EVENT_DATE]) == ["2026-01-06", "2026-01-07"]


def test_multiple_symbols_read_together_stay_separated():
    store.write(store.DAILY_BARS, "AAPL", [_bar("2026-01-05", 100.0)],
                fetched_at=_t("2026-01-05"))
    store.write(store.DAILY_BARS, "MSFT",
                [{"symbol": "MSFT", store.EVENT_DATE: "2026-01-05",
                  "close": 200.0, "source": "test"}],
                fetched_at=_t("2026-01-05"))
    frame = store.read(store.DAILY_BARS, ["AAPL", "MSFT"], as_of=_t("2026-01-06"))
    assert dict(zip(frame["symbol"], frame["close"])) == {"AAPL": 100.0, "MSFT": 200.0}


def test_a_symbol_with_a_slash_or_dash_round_trips():
    """OKX instrument ids contain dashes; A-share codes are numeric strings."""
    for symbol in ("SOL-USDT", "600519", "BTC-USDT-SWAP"):
        store.write(store.DAILY_BARS, symbol,
                    [{"symbol": symbol, store.EVENT_DATE: "2026-01-05",
                      "close": 1.0, "source": "test"}],
                    fetched_at=_t("2026-01-05"))
    assert set(store.symbols(store.DAILY_BARS)) == {"SOL-USDT", "600519", "BTC-USDT-SWAP"}


def test_missing_values_stay_null_through_a_round_trip():
    """The project's standing rule, enforced at the storage boundary.

    A bar with no volume must not come back as 0 — a real zero-volume session and
    an unreported one are different facts, and only one of them is a halt.
    """
    store.write(store.DAILY_BARS, "AAPL",
                [{"symbol": "AAPL", store.EVENT_DATE: "2026-01-05",
                  "close": 100.0, "volume": None, "source": "test"}],
                fetched_at=_t("2026-01-05"))
    frame = store.read(store.DAILY_BARS, "AAPL", as_of=_t("2026-01-06"))
    assert frame["volume"].isna().all()


def test_coverage_reports_both_time_axes():
    store.write(store.DAILY_BARS, "AAPL",
                [_bar("2026-01-05", 100.0), _bar("2026-01-06", 101.0)],
                fetched_at=_t("2026-01-06"))
    c = store.coverage(store.DAILY_BARS)
    assert c["rows"] == 2 and c["symbols"] == 1
    assert (c["start"], c["end"]) == ("2026-01-05", "2026-01-06")
    assert c["first_fetch"] and c["last_fetch"]


def test_coverage_of_an_empty_dataset_is_zero_not_an_error():
    c = store.coverage(store.FUNDING_RATES)
    assert c["rows"] == 0 and c["start"] is None
