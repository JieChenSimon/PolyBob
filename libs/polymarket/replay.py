"""Deterministic replay of logged raw book events.

Reruns raw events captured by ``libs.db.book_log.BookEventLog`` through the
SAME reducer used by the live ingestor (``PolymarketBookReducer``) — a single
implementation, so replay is bit-for-bit deterministic given the same log:
identical inputs produce identical book-state sequences and book hashes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Iterator, Protocol

from libs.polymarket.book_state import BookState, PolymarketBookReducer


class _RawEvent(Protocol):
    asset_id: str | None
    event_type: str
    payload: dict
    receive_ts: datetime


_BOOK_EVENT_TYPES = {"book"}
_PRICE_CHANGE_EVENT_TYPES = {"price_change"}


def replay_book_states(events: Iterable[_RawEvent]) -> Iterator[BookState]:
    """Replay raw events in order, yielding each resulting book state.

    Uses the logged ``receive_ts`` (not wall-clock time), so the output is a
    pure function of the log contents. Non-book events (trades etc.) are
    skipped — they do not affect book state.
    """
    reducer = PolymarketBookReducer()
    for event in events:
        if event.event_type in _BOOK_EVENT_TYPES:
            state = reducer.apply_snapshot(
                event.payload,
                receive_ts=event.receive_ts,
                asset_id=event.asset_id or event.payload.get("asset_id"),
            )
            if state is not None:
                yield state
        elif event.event_type in _PRICE_CHANGE_EVENT_TYPES:
            yield from reducer.apply_price_change(
                event.payload, receive_ts=event.receive_ts
            )


def replay_from_log(
    book_log,
    asset_id: str,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[BookState]:
    """Replay all logged events for one asset; returns the state sequence."""
    return list(replay_book_states(book_log.read_events(asset_id, start=start, end=end)))
