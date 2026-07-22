"""P12: persistent WAL writer, no per-write schema init / connection churn."""

from __future__ import annotations

import json

import pytest

from libs.db import (
    append_audit_event,
    append_audit_events,
    close_writer_connections,
    connect,
)
from libs.db import fact_store


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "writer.sqlite3"
    yield path
    # Release the persistent writer connection created during the test.
    close_writer_connections(path)


def test_schema_not_reinitialized_per_write(db_path, monkeypatch):
    calls = {"count": 0}
    real_init_db = fact_store.init_db

    def counting_init_db(path=None):
        calls["count"] += 1
        return real_init_db(path)

    monkeypatch.setattr(fact_store, "init_db", counting_init_db)

    ids = [append_audit_event(f"e{i}", db_path=db_path) for i in range(5)]

    assert ids == [1, 2, 3, 4, 5]
    # init_db runs at most once for the path, not once per append.
    assert calls["count"] == 1


def test_writer_connection_is_reused(db_path, monkeypatch):
    connect_calls = {"count": 0}
    real_connect = fact_store.connect

    def counting_connect(path=None, **kwargs):
        connect_calls["count"] += 1
        return real_connect(path, **kwargs)

    monkeypatch.setattr(fact_store, "connect", counting_connect)

    for i in range(4):
        append_audit_event(f"reuse-{i}", db_path=db_path)
    after_four = connect_calls["count"]

    for i in range(4, 12):
        append_audit_event(f"reuse-{i}", db_path=db_path)
    after_twelve = connect_calls["count"]

    # Connections are opened once (one-time schema init + the persistent
    # writer) and then reused: the count does not grow with the write count.
    assert after_four == after_twelve
    assert after_twelve <= 2


def test_append_is_readable_from_a_fresh_connection(db_path):
    append_audit_event("case.created", payload={"k": "v"}, db_path=db_path)

    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT payload_json FROM audit_events WHERE event_type = ?",
            ("case.created",),
        ).fetchone()
    assert json.loads(row["payload_json"]) == {"k": "v"}


def test_batch_append_writes_all_events_in_one_go(db_path):
    written = append_audit_events(
        [
            {"event_type": "a", "payload": {"n": 1}},
            {"event_type": "b", "actor": "worker", "subject_id": "s-1"},
            {"event_type": "c"},
        ],
        db_path=db_path,
    )
    assert written == 3

    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT event_type, actor FROM audit_events ORDER BY id"
        ).fetchall()
    assert [r["event_type"] for r in rows] == ["a", "b", "c"]
    assert rows[1]["actor"] == "worker"


def test_batch_append_empty_is_noop(db_path):
    assert append_audit_events([], db_path=db_path) == 0


def test_close_writer_connections_allows_fresh_writer(db_path):
    append_audit_event("first", db_path=db_path)
    close_writer_connections(db_path)
    # A new persistent connection is transparently opened; ids keep counting up.
    second = append_audit_event("second", db_path=db_path)
    assert second == 2
