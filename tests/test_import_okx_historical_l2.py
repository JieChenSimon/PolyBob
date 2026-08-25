import json

from scripts.import_okx_historical_l2 import _download, download_links


class _Response:
    def __init__(self, payload: bytes | dict):
        self._payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.headers = {"Content-Length": str(len(self._payload))}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size=-1):
        if not self._payload:
            return b""
        if size is None or size < 0:
            value, self._payload = self._payload, b""
        else:
            value, self._payload = self._payload[:size], self._payload[size:]
        return value

    def __iter__(self):
        return iter((self._payload,))


def test_download_links_uses_real_orderbook_module_and_ms_dates(monkeypatch):
    captured = {}
    response = _Response({
        "code": "0",
        "data": {"details": [{"instId": "BTC-USDT", "groupDetails": [{
            "url": "https://static.okx.com/a.tar.gz",
            "filename": "a.tar.gz", "sizeMB": "1.2", "dateTs": "1",
        }]}]},
    })

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        return response

    monkeypatch.setattr("scripts.import_okx_historical_l2.urllib.request.urlopen", fake_urlopen)
    links = download_links(["BTC-USDT"], inst_type="SPOT",
                           begin="2025-08-01", end="2025-08-02", depth=400)

    assert captured["body"]["module"] == "4"
    assert captured["body"]["dateQuery"]["begin"] == "1754006400000"
    assert links[0]["inst_id"] == "BTC-USDT"


def test_download_streams_to_atomic_target_and_enforces_size(monkeypatch, tmp_path):
    payload = b"real-archive-bytes"
    monkeypatch.setattr(
        "scripts.import_okx_historical_l2.urllib.request.urlopen",
        lambda request, timeout: _Response(payload),
    )
    target = tmp_path / "archive.tar.gz"
    result = _download("https://static.okx.com/archive.tar.gz", target, max_bytes=1024)

    assert target.read_bytes() == payload
    assert result["bytes"] == len(payload)
    assert not list(tmp_path.glob("*.pending"))
