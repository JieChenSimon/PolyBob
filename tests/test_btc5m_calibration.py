import json

import numpy as np

from scripts import btc5m_calibration


def test_fetch_1m_uses_bounded_http_client_and_preserves_real_rows(monkeypatch):
    calls = []
    payload = {
        "code": "0",
        "data": [
            ["120000", "102", "0", "0", "103", "1"],
            ["60000", "100", "0", "0", "101", "1"],
        ],
    }

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return json.dumps(payload).encode()

    monkeypatch.setattr(btc5m_calibration, "http_get_bytes", fake_get)
    monkeypatch.setattr(btc5m_calibration, "record_raw", lambda *args, **kwargs: None)

    result = btc5m_calibration.fetch_1m("BTCUSDT", minutes=2)

    assert isinstance(result, np.ndarray)
    assert result[:, 0].tolist() == [60000.0, 120000.0]
    assert len(calls) == 1
    assert calls[0][1]["timeout"] == 60.0
    assert calls[0][1]["headers"]["User-Agent"] == "PolyBobCal/0.1"
