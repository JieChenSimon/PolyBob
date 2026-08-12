from argparse import Namespace
from pathlib import Path
import subprocess

from scripts.dev_control import DevelopmentControl


def repo(tmp_path: Path) -> DevelopmentControl:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "config.yml").write_text("schema: 1\nwip: 1\n")
    (tmp_path / "seed").write_text("x")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=tmp_path, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=tmp_path, check=True)
    return DevelopmentControl(tmp_path)


def add_remote(tasks: DevelopmentControl, tmp_path: Path) -> Path:
    remote = tmp_path.parent / f"{tmp_path.name}-remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=tmp_path, check=True)
    subprocess.run(["git", "push", "-qu", "origin", "main"], cwd=tmp_path, check=True)
    return remote


def create(tasks: DevelopmentControl, title: str = "Small task", deps=None):
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
    add_remote(tasks, tmp_path)
    task = create(tasks)
    tasks.move(task["id"], "doing")
    (tmp_path / "selected").write_text("yes")
    tasks.commit(task["id"], "pushable", ["selected"])
    target = tasks.push(task["id"], "origin")
    branch = tasks.git("branch", "--show-current")
    assert target == f"origin/{branch}"
    assert tasks.git("rev-parse", "--abbrev-ref", "@{u}") == f"origin/{branch}"


def test_branch_decision_uses_remote_main_and_neutral_name(tmp_path):
    tasks = repo(tmp_path)
    add_remote(tasks, tmp_path)
    task = create(tasks, "Codex branch choice")
    action, detail = tasks.branch_plan(task["id"], fetch=True)
    assert action == "CREATE"
    assert detail.endswith("from origin/main")
    name = tasks.start_branch(task["id"])
    assert name.startswith(f"{task['id'].lower()}-")
    assert "codex" not in name
    assert tasks.git("rev-parse", "HEAD") == tasks.git("rev-parse", "origin/main")


def test_branch_plan_blocks_unrelated_dirty_work(tmp_path):
    tasks = repo(tmp_path)
    task = create(tasks)
    (tmp_path / "unrelated").write_text("keep")
    assert tasks.branch_plan(task["id"])[0] == "BLOCK"


def test_doctor_detects_unpublished_main_and_promote_is_explicit_ff(tmp_path, capsys):
    tasks = repo(tmp_path)
    add_remote(tasks, tmp_path)
    task = create(tasks, "Publish branch")
    tasks.start_branch(task["id"])
    (tmp_path / "selected").write_text("yes")
    head = tasks.commit(task["id"], "publishable", ["selected"])
    assert any("use promote" in message for _, message in tasks.doctor())
    before = tasks.git("rev-parse", "origin/main")
    assert tasks.promote(task["id"], "main", "origin", False) is None
    assert tasks.git("rev-parse", "origin/main") == before
    assert "dry run" in capsys.readouterr().out
    assert tasks.promote(task["id"], "main", "origin", True) == "origin/main"
    tasks.git("fetch", "origin")
    assert tasks.git("rev-parse", "origin/main") == head


def test_promote_rejects_diverged_target(tmp_path):
    tasks = repo(tmp_path)
    add_remote(tasks, tmp_path)
    task = create(tasks, "Diverged branch")
    branch = tasks.start_branch(task["id"])
    (tmp_path / "selected").write_text("yes")
    tasks.commit(task["id"], "task change", ["selected"])
    tasks.git("switch", "main")
    (tmp_path / "base-only").write_text("remote change")
    tasks.git("add", "base-only"); tasks.git("commit", "-m", "advance main"); tasks.git("push", "origin", "main")
    tasks.git("switch", branch)
    assert "not fast-forward" in _failure(lambda: tasks.promote(task["id"], "main", "origin", True))


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
