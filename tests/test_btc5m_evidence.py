"""The BTC-5m row must be verifiable, and its sample honestly counted.

This edge sat on the board for the whole life of the project reporting n=95 and
t=3.45 against a 3.60 hurdle — "nearly significant", which is the most dangerous
thing a result can be, because it invites one more month of data rather than a
second look at the denominator.

The second look was overdue twice. It kept no per-event data, so the board could not
recompute its statistic and had to take 3.45 on trust; and when the events were
finally kept, all 99 qualifying trades turned out to come from **2 calendar days** of
Polymarket history. n=95 was two observations wearing a 95-sized disguise.
"""

from __future__ import annotations

import json
from pathlib import Path

RESULT = Path("data/btc5m_mispricing.json")
BOARD = Path("data/promotion_board.json")


def _row():
    board = json.loads(BOARD.read_text())
    return next(r for r in board["board"] if r["strategy"] == "btc5m_mispricing")


def test_the_result_file_carries_per_event_data():
    """Without it the board cannot verify the statistic, only copy it."""
    payload = json.loads(RESULT.read_text())
    events = payload["result"].get("events")
    assert isinstance(events, list) and events
    for event in events[:5]:
        assert event["date"] and event["excess"] is not None


def test_every_event_carries_the_window_date():
    """The date is what makes the standard error computable at all."""
    payload = json.loads(RESULT.read_text())
    dates = {e["date"] for e in payload["result"]["events"]}
    assert all(len(d) == 10 and d.count("-") == 2 for d in dates)


def test_the_board_can_now_verify_this_row():
    """``no_per_event_data_cannot_verify_t`` must no longer be the reason it fails."""
    row = _row()
    assert row["inference"] == "cluster_robust"
    assert "no_per_event_data_cannot_verify_t" not in row["failed"]
    assert row["t_stat"] is not None
    assert row["n_clusters"] is not None


def test_five_minute_windows_are_clustered_by_day():
    """Consecutive windows share one price path and one volatility regime.

    A 5-minute binary settles inside the session, so the unit that is actually
    independent is the day. Windows minutes apart are not independent draws however
    many of them you collect.
    """
    row = _row()
    assert row["cluster_by"] == "day"


def test_the_clustered_statistic_is_the_weaker_one():
    """If clustering raised the t-statistic it would not be doing what it claims."""
    row = _row()
    assert abs(row["t_stat"]) <= abs(row["t_stat_iid"]) + 1e-9


def test_a_two_day_sample_cannot_clear_the_gate():
    """The finding that matters: 99 trades over 2 days is not a sample.

    If this ever passes, either Polymarket history has genuinely broadened to 20+
    distinct days — in which case update this test deliberately — or the cluster
    floor has been weakened, which is the failure this whole apparatus exists to
    prevent.
    """
    row = _row()
    assert row["approved"] is False
    if row["n_clusters"] < 20:
        assert f"independent_clusters<20" in row["failed"]
