from apps.api import dev_control_api


def test_development_control_is_a_compact_derived_projection():
    import asyncio

    payload = asyncio.run(dev_control_api.control_state())
    assert payload["tasks"]
    assert sum(payload["counts"].values()) == len(payload["tasks"])
    assert 0 <= payload["completion_pct"] <= 100
    assert all(task["progress"]["total"] == len(task["checks"]) for task in payload["tasks"])
    assert all(task["delivery"] in {"uncommitted", "local", "pushed", "main"}
               for task in payload["tasks"])
