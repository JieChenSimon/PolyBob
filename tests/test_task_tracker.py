from argparse import Namespace
from pathlib import Path
import subprocess

from scripts.task_tracker import Tasks


def repo(tmp_path: Path) -> Tasks:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "config.yml").write_text("schema: 1\nwip: 1\n")
    (tmp_path / "seed").write_text("x")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=tmp_path, check=True)
    return Tasks(tmp_path)


def create(tasks: Tasks, title: str = "Small task", deps=None):
    return tasks.create(Namespace(title=title, why="Measured reason", check=["Tests pass"],
                                  dep=deps or [], priority="P1", area="core"))


def test_task_needs_check_dependency_and_commit_to_finish(tmp_path):
    tasks = repo(tmp_path)
    first = create(tasks)
    tasks.move(first["id"], "doing")
    task = tasks.load(first["id"]); task["checks"][0]["done"] = True; tasks.save(task)
    assert "no Git commit" in _failure(lambda: tasks.move(first["id"], "done"))

    (tmp_path / "change").write_text("done")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", f"work\n\nPolyBob-Task: {first['id']}"], cwd=tmp_path, check=True)
    assert tasks.move(first["id"], "done")["state"] == "done"
    assert tasks.validate() == []


def test_wip_and_dependency_are_fail_closed(tmp_path):
    tasks = repo(tmp_path)
    first = create(tasks, "First")
    second = create(tasks, "Second", [first["id"]])
    tasks.move(first["id"], "doing")
    assert "WIP full" in _failure(lambda: tasks.move(second["id"], "doing"))


def test_stop_only_changes_task_state(tmp_path):
    tasks = repo(tmp_path)
    task = create(tasks)
    tasks.move(task["id"], "doing")
    before = (tmp_path / "seed").read_text()
    stopped = tasks.stop(task["id"], "scope removed")
    assert stopped["state"] == "dropped"
    assert stopped["blocked"] == "scope removed"
    assert (tmp_path / "seed").read_text() == before


def test_rollback_previews_then_creates_revert_commit(tmp_path, capsys):
    tasks = repo(tmp_path)
    task = create(tasks)
    tasks.move(task["id"], "doing")
    tracked = tasks.load(task["id"]); tracked["checks"][0]["done"] = True; tasks.save(tracked)
    (tmp_path / "change").write_text("task work")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", f"work\n\nPolyBob-Task: {task['id']}"], cwd=tmp_path, check=True)

    assert tasks.rollback(task["id"], False) is None
    assert (tmp_path / "change").exists()
    assert "dry run" in capsys.readouterr().out

    rolled_back = tasks.rollback(task["id"], True)
    assert rolled_back and rolled_back["state"] == "dropped"
    assert not (tmp_path / "change").exists()
    assert tasks.git("status", "--porcelain") == ""
    assert "rollback task" in tasks.git("log", "-1", "--format=%s")


def test_rollback_refuses_dirty_worktree(tmp_path):
    tasks = repo(tmp_path)
    task = create(tasks)
    (tmp_path / "change").write_text("task work")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", f"work\n\nPolyBob-Task: {task['id']}"], cwd=tmp_path, check=True)
    (tmp_path / "user-note").write_text("keep me")
    assert "worktree is not clean" in _failure(lambda: tasks.rollback(task["id"], True))
    assert (tmp_path / "change").exists()
    assert (tmp_path / "user-note").read_text() == "keep me"


def test_commit_stages_only_explicit_paths_and_adds_trailer(tmp_path):
    tasks = repo(tmp_path)
    task = create(tasks)
    tasks.move(task["id"], "doing")
    (tmp_path / "selected").write_text("yes")
    (tmp_path / "untouched").write_text("no")
    sha = tasks.commit(task["id"], "focused change", ["selected"])
    assert tasks.git("show", "--format=", "--name-only", sha).splitlines() == [
        "selected", f"tasks/items/{task['id']}.yml"
    ]
    assert f"PolyBob-Task: {task['id']}" in tasks.git("show", "-s", "--format=%B", sha)
    assert "?? untouched" in tasks.git("status", "--porcelain")


def test_push_sets_upstream_for_task_branch(tmp_path):
    tasks = repo(tmp_path)
    remote = tmp_path.parent / f"{tmp_path.name}-remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=tmp_path, check=True)
    task = create(tasks)
    tasks.move(task["id"], "doing")
    (tmp_path / "selected").write_text("yes")
    tasks.commit(task["id"], "pushable", ["selected"])
    target = tasks.push(task["id"], "origin")
    branch = tasks.git("branch", "--show-current")
    assert target == f"origin/{branch}"
    assert tasks.git("rev-parse", "--abbrev-ref", "@{u}") == f"origin/{branch}"


def test_doctor_fixes_hook_and_git_abort_ends_conflict(tmp_path):
    tasks = repo(tmp_path)
    report = tasks.doctor(fix=True)
    assert ("FIXED", "enabled .githooks") in report
    assert tasks.git("config", "--local", "--get", "core.hooksPath") == ".githooks"

    base = tasks.git("branch", "--show-current")
    subprocess.run(["git", "switch", "-c", "other"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "seed").write_text("other")
    subprocess.run(["git", "commit", "-qam", "other"], cwd=tmp_path, check=True)
    subprocess.run(["git", "switch", base], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "seed").write_text("base")
    subprocess.run(["git", "commit", "-qam", "base"], cwd=tmp_path, check=True)
    merge = subprocess.run(["git", "merge", "other"], cwd=tmp_path, capture_output=True)
    assert merge.returncode != 0
    assert tasks.operation() == "merge"
    assert tasks.abort_git() == "merge"
    assert tasks.operation() is None
    assert tasks.git("status", "--porcelain") == ""


def _failure(call):
    try:
        call()
    except RuntimeError as exc:
        return str(exc)
    raise AssertionError("expected failure")
