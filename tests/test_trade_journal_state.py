from pathlib import Path

import pytest

from libs.db.trade_journal import TradeJournal


def _journal(tmp_path: Path) -> TradeJournal:
    return TradeJournal(tmp_path / "journal.sqlite3")


def test_fill_is_not_applied_twice(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    entry = journal.open_entry(
        edge_id="edge-1", symbol="BTC", domain="crypto", direction="long", qty=1
    )
    journal.record_fill(entry.entry_id, price=100, fees=1)

    with pytest.raises(ValueError, match="duplicate fees"):
        journal.record_fill(entry.entry_id, price=100, fees=1)

    stored = journal.get(entry.entry_id)
    assert stored is not None
    assert stored.fees == 1


def test_close_requires_filled_open_position_and_is_not_replayed(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    planned = journal.open_entry(
        edge_id="edge-1", symbol="BTC", domain="crypto", direction="long", qty=1
    )
    with pytest.raises(ValueError, match="not an open filled position"):
        journal.close_entry(planned.entry_id, price=110, fees=1)

    journal.record_fill(planned.entry_id, price=100, fees=1)
    journal.close_entry(planned.entry_id, price=110, fees=2)
    with pytest.raises(ValueError, match="duplicate exit fees"):
        journal.close_entry(planned.entry_id, price=110, fees=2)

    stored = journal.get(planned.entry_id)
    assert stored is not None
    assert stored.fees == 3


def test_abandon_cannot_rewrite_an_executed_entry(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    entry = journal.open_entry(
        edge_id="edge-1", symbol="BTC", domain="crypto", direction="long", qty=1
    )
    journal.record_fill(entry.entry_id, price=100)
    with pytest.raises(ValueError, match="only planned entries"):
        journal.abandon(entry.entry_id)
