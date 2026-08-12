from apps.api import tasks_api


def test_task_board_is_a_compact_derived_projection():
    import asyncio

    payload = asyncio.run(tasks_api.task_board())
    assert payload["tasks"]
    assert sum(payload["counts"].values()) == len(payload["tasks"])
    assert 0 <= payload["completion_pct"] <= 100
    assert all(task["progress"]["total"] == len(task["checks"]) for task in payload["tasks"])
