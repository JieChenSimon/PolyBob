"""P6: the orphaned /ws/market websocket endpoint has been removed.

The dashboard's useWebSocket hook was deleted and nothing else consumes the
endpoint, so the per-connection 2s upstream poller is gone.
"""
from apps.api.main import app


def test_ws_market_route_is_removed():
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/ws/market" not in paths


def test_no_websocket_routes_remain():
    from starlette.routing import WebSocketRoute

    ws_routes = [r for r in app.routes if isinstance(r, WebSocketRoute)]
    assert ws_routes == []
