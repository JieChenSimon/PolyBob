from libs.db import connect
from libs.forecasting.state_store import ForecastInstrumentStore


def test_missing_instrument_is_disabled_and_persists_opt_in(tmp_path):
    db_path = tmp_path / "forecast.sqlite3"
    store = ForecastInstrumentStore(db_path)

    missing = store.get("us_equity", "aapl")
    assert missing.enabled is False
    assert missing.horizon == 5
    assert missing.updated_at is None

    saved = store.set("us_equity", "aapl", enabled=True, horizon=10)
    reopened = ForecastInstrumentStore(db_path).get("us_equity", "AAPL")

    assert saved.enabled is True
    assert reopened == saved
    with connect(db_path) as connection:
        audit = connection.execute(
            "SELECT event_type, subject_id FROM audit_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert audit["event_type"] == "forecast.instrument_configured"
    assert audit["subject_id"] == "us_equity:AAPL"


def test_enabled_instruments_are_filtered_by_domain(tmp_path):
    store = ForecastInstrumentStore(tmp_path / "forecast.sqlite3")
    store.set("us_equity", "AAPL", enabled=True, horizon=5)
    store.set("crypto_spot", "BTC-USDT", enabled=True, horizon=1)
    store.set("us_equity", "MSFT", enabled=False, horizon=5)

    assert [row.symbol for row in store.list_enabled("us_equity")] == ["AAPL"]
    assert [row.symbol for row in store.list_enabled()] == ["BTC-USDT", "AAPL"]
