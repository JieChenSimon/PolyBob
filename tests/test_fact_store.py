import json

from libs.db import append_audit_event, connect, init_db
from libs.db import fact_store


EXPECTED_TABLES = {
    "investment_cases",
    "decisions",
    "orders",
    "fills",
    "ledger_entries",
    "audit_events",
    "intents",
    "baskets",
    "basket_legs",
    "strategy_decisions",
}


def test_init_db_is_idempotent(tmp_path):
    db_path = tmp_path / "polybob.sqlite3"

    first_path = init_db(db_path)
    second_path = init_db(db_path)

    assert first_path == db_path
    assert second_path == db_path
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            """
        ).fetchall()

    assert {row["name"] for row in rows} == EXPECTED_TABLES


def test_append_audit_event_persists_payload(tmp_path):
    db_path = tmp_path / "polybob.sqlite3"

    event_id = append_audit_event(
        "case.created",
        actor="test",
        subject_type="investment_case",
        subject_id="case-1",
        payload={"confidence": 0.72, "tags": ["btc", "polymarket"]},
        db_path=db_path,
    )

    assert event_id == 1
    with connect(db_path) as connection:
        row = connection.execute("SELECT * FROM audit_events WHERE id = ?", (event_id,)).fetchone()

    assert row["event_type"] == "case.created"
    assert row["actor"] == "test"
    assert row["subject_type"] == "investment_case"
    assert row["subject_id"] == "case-1"
    assert json.loads(row["payload_json"]) == {
        "confidence": 0.72,
        "tags": ["btc", "polymarket"],
    }
    assert row["created_at"]


def test_audit_event_is_readable_after_reopening_connection(tmp_path):
    db_path = tmp_path / "polybob.sqlite3"
    event_id = append_audit_event("decision.recorded", payload={"decision": "watch"}, db_path=db_path)

    with connect(db_path) as connection:
        first_read = connection.execute(
            "SELECT payload_json FROM audit_events WHERE id = ?",
            (event_id,),
        ).fetchone()

    with connect(db_path) as reopened:
        second_read = reopened.execute(
            "SELECT payload_json FROM audit_events WHERE id = ?",
            (event_id,),
        ).fetchone()

    assert json.loads(first_read["payload_json"]) == {"decision": "watch"}
    assert json.loads(second_read["payload_json"]) == {"decision": "watch"}


def test_append_audit_event_initializes_schema_once(tmp_path, monkeypatch):
    db_path = tmp_path / "polybob.sqlite3"
    calls = {"count": 0}
    real_init_db = fact_store.init_db

    def counting_init_db(path=None):
        calls["count"] += 1
        return real_init_db(path)

    monkeypatch.setattr(fact_store, "init_db", counting_init_db)

    first_id = append_audit_event("one", db_path=db_path)
    second_id = append_audit_event("two", db_path=db_path)

    assert (first_id, second_id) == (1, 2)
    assert calls["count"] == 1
