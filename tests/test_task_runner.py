from modules.task_runner import TaskRunner
from datetime import datetime, timedelta

from libs.quant.data_slo import evaluate_slo


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


def test_task_runner_retries_timeout_and_recovers_running(tmp_path):
    runner = TaskRunner(tmp_path / "jobs.sqlite3")
    result = runner.run(
        job_id="j2", idempotency_key="retry", kind="forecast", payload={},
        handler=lambda _: (_ for _ in ()).throw(RuntimeError("temporary")), retries=1,
    )
    assert result["status"] == "failed"
    assert result["attempts"] == 2
    assert runner.store.list_runs(kind="forecast")[0]["attempts"] == 2
    runner.store.enqueue(job_id="j3", idempotency_key="stale", kind="collect")
    runner.store.transition("j3", "running")
    assert runner.store.recover_running() == 1


def test_data_slo_reports_freshness_coverage_failures_and_duplicates():
    now = datetime(2026, 8, 24, 0, 0, 10)
    report = evaluate_slo(
        [{"id": "a", "timestamp": now - timedelta(seconds=1)},
         {"id": "a", "timestamp": now - timedelta(seconds=1), "status": "failed"}],
        now=now, expected_count=3, freshness_budget=timedelta(seconds=5),
        model_runs=2, model_failures=1,
    )
    assert report.status == "alert"
    assert report.coverage < 1
    assert report.duplicate_rate > 0
    assert "model_runs_failed" in report.alerts
