from modules.task_runner import TaskRunner


def test_task_runner_is_idempotent_and_persists_failure_and_feature_replay(tmp_path):
    runner = TaskRunner(tmp_path / "jobs.sqlite3")
    calls = []
    first = runner.run(job_id="j1", idempotency_key="bars:BTC:1m:1", kind="collect", payload={"x": 1}, handler=lambda p: calls.append(p))
    second = runner.run(job_id="j2", idempotency_key="bars:BTC:1m:1", kind="collect", payload={"x": 2}, handler=lambda p: calls.append(p))
    assert first["status"] == "succeeded"
    assert second["job_id"] == "j1"
    assert calls == [{"x": 1}]
    assert runner.store.record_feature(snapshot_id="s1", instrument_id="BTC", observed_at="2026-08-24T00:00:00Z", payload={"close": 1}, source="test")
    assert not runner.store.record_feature(snapshot_id="s1", instrument_id="BTC", observed_at="2026-08-24T00:00:00Z", payload={"close": 2}, source="test")
    assert runner.store.replay_feature("s1")["payload"] == {"close": 1}
