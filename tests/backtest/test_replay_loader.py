from datetime import datetime, timedelta
import json

import pytest

from libs.backtest.replay import HistoricalDataReplayer


def test_replay_loader_reads_json_and_filters_time_range(tmp_path):
    start = datetime(2026, 1, 1)
    path = tmp_path / "events.json"
    path.write_text(json.dumps([
        {"timestamp": "2025-12-31T23:59:00", "topic": "market", "data": {"x": 0}},
        {"timestamp": "2026-01-01T00:00:01", "topic": "market", "data": {"x": 1}},
    ]))
    replay = HistoricalDataReplayer(str(path), start, start + timedelta(minutes=1))
    events = replay.load_data()
    assert len(events) == 1
    assert events[0]["data"] == {"x": 1}


def test_replay_loader_fails_closed_on_empty_range(tmp_path):
    path = tmp_path / "events.json"
    path.write_text(json.dumps([]))
    replay = HistoricalDataReplayer(str(path), datetime(2026, 1, 1), datetime(2026, 1, 2))
    with pytest.raises(ValueError, match="no events"):
        replay.load_data()
