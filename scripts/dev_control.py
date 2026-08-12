#!/usr/bin/env python3
"""PolyBob Development Control: tasks, Git, delivery, and recovery."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

ID = re.compile(r"^PB-(\d{4})$")
BRANCH_ID = re.compile(r"(?:^|/)(pb-\d{4})(?:-|$)", re.I)
STATES = ("todo", "doing", "blocked", "done", "dropped")
PRIORITIES = ("P0", "P1", "P2", "P3")
FORBIDDEN_BRANCH_WORDS = ("codex", "claude", "openai", "chatgpt")
MOVES = {
    "todo": {"doing", "dropped"},
    "doing": {"blocked", "done", "dropped"},
    "blocked": {"doing", "dropped"},
    "done": {"todo"},
    "dropped": {"todo"},
}


class Error(RuntimeError):
    pass


def stamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


class DevelopmentControl:
    def __init__(self, root: Path):
        self.root = root
        self.directory = root / "tasks" / "items"

    def git(self, *args: str, fail: bool = True) -> str:
        run = subprocess.run(["git", *args], cwd=self.root, text=True,
                             capture_output=True, check=False)
        if fail and run.returncode:
            raise Error(run.stderr.strip() or "git command failed")
        return run.stdout.strip()

    def path(self, task_id: str) -> Path:
        task_id = task_id.upper()
        if not ID.fullmatch(task_id):
            raise Error(f"bad id: {task_id}")
        return self.directory / f"{task_id}.yml"

    def load(self, task_id: str) -> dict:
        path = self.path(task_id)
        if not path.exists():
            raise Error(f"not found: {task_id.upper()}")
        task = yaml.safe_load(path.read_text())
        if not isinstance(task, dict):
            raise Error(f"bad task file: {path}")
        return task

    def save(self, task: dict) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        task["updated"] = stamp()
        self.path(task["id"]).write_text(
            yaml.safe_dump(task, allow_unicode=True, sort_keys=False, width=100)
        )

    def all(self) -> list[dict]:
        if not self.directory.exists():
            return []
        return [yaml.safe_load(path.read_text()) for path in sorted(self.directory.glob("PB-*.yml"))]

    def next_id(self) -> str:
        nums = [int(m.group(1)) for path in self.directory.glob("PB-*.yml")
                if (m := ID.fullmatch(path.stem))]
        return f"PB-{max(nums, default=0) + 1:04d}"

    def commits(self, task_id: str) -> list[dict[str, str]]:
        raw = self.git("log", "--all", "--format=%H%x09%ad%x09%s", "--date=short",
                       f"--grep=PolyBob-Task: {task_id}", fail=False)
        return [{"sha": a, "date": b, "subject": c} for line in raw.splitlines()
                if len(parts := line.split("\t", 2)) == 3 for a, b, c in [parts]]

    def remote(self) -> str | None:
        configured = self.git("config", "--get", f"branch.{self.config().get('base', 'main')}.remote",
                              fail=False)
        if configured and configured != ".": return configured
        upstream = self.git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", fail=False)
        if "/" in upstream: return upstream.split("/", 1)[0]
        remotes = self.git("remote", fail=False).splitlines()
        return remotes[0] if remotes else None

    def ref_exists(self, ref: str) -> bool:
        return subprocess.run(["git", "show-ref", "--verify", "--quiet", ref],
                              cwd=self.root, check=False).returncode == 0

    def base_ref(self, remote: str | None = None) -> str:
        base = str(self.config().get("base", "main"))
        remote = remote or self.remote()
        if remote and self.ref_exists(f"refs/remotes/{remote}/{base}"):
            return f"{remote}/{base}"
        if self.ref_exists(f"refs/heads/{base}"):
            return base
        raise Error(f"base branch not found: {base}")

    def branch_name(self, task: dict) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", task["title"].lower()).strip("-")[:40] or "task"
        forbidden = [str(value).lower() for value in self.config().get(
            "forbidden_branch_words", FORBIDDEN_BRANCH_WORDS
        )]
        parts = [part for part in slug.split("-") if part and part not in forbidden]
        return f"{task['id'].lower()}-{'-'.join(parts) or 'task'}"

    def branch_plan(self, task_id: str, fetch: bool = False) -> tuple[str, str]:
        task = self.load(task_id)
        remote = self.remote()
        if fetch and remote:
            self.git("fetch", remote, "--prune")
        current = self.git("branch", "--show-current", fail=False)
        desired = task.get("branch") or self.branch_name(task)
        if self.operation(): return "BLOCK", f"{self.operation()} in progress"
        own_file = str(self.path(task["id"]).relative_to(self.root))
        dirty = [line[3:] for line in self.git("status", "--porcelain", "--untracked-files=all", fail=False).splitlines()
                 if line[3:] != own_file]
        if dirty: return "BLOCK", f"worktree has unrelated changes: {len(dirty)}"
        if current == desired: return "REUSE", desired
        if self.ref_exists(f"refs/heads/{desired}"): return "SWITCH", desired
        if remote and self.ref_exists(f"refs/remotes/{remote}/{desired}"):
            return "TRACK", f"{remote}/{desired}"
        if task.get("branch"): return "BLOCK", f"recorded branch missing: {desired}"
        return "CREATE", f"{desired} from {self.base_ref(remote)}"

    def start_branch(self, task_id: str) -> str:
        task = self.load(task_id)
        if task["state"] != "todo": raise Error(f"branch needs todo, got {task['state']}")
        limit = int(self.config().get("wip", 3))
        if sum(t["state"] == "doing" for t in self.all()) >= limit: raise Error("WIP full")
        action, detail = self.branch_plan(task_id, fetch=True)
        if action == "BLOCK": raise Error(detail)
        desired = task.get("branch") or self.branch_name(task)
        if action == "SWITCH": self.git("switch", desired)
        elif action == "TRACK": self.git("switch", "--track", "-c", desired, detail)
        elif action == "CREATE": self.git("switch", "--no-track", "-c", desired, detail.rsplit(" from ", 1)[1])
        task["branch"] = desired; task["state"] = "doing"; self.save(task)
        return desired

    def operation(self) -> str | None:
        checks = {
            "merge": "MERGE_HEAD", "rebase": "rebase-merge", "rebase-apply": "rebase-apply",
            "cherry-pick": "CHERRY_PICK_HEAD", "revert": "REVERT_HEAD",
        }
        for name, marker in checks.items():
            path = Path(self.git("rev-parse", "--git-path", marker))
            if not path.is_absolute(): path = self.root / path
            if path.exists():
                return "rebase" if name.startswith("rebase") else name
        return None

    def doctor(self, fix: bool = False, fetch: bool = False) -> list[tuple[str, str]]:
        report: list[tuple[str, str]] = []
        if fetch:
            self.git("fetch", "--prune")
            report.append(("OK", "remote refs refreshed"))
        branch = self.git("branch", "--show-current", fail=False)
        if not branch:
            report.append(("BLOCK", "detached HEAD; switch to a named branch"))
        operation = self.operation()
        conflicts = self.git("diff", "--name-only", "--diff-filter=U", fail=False).splitlines()
        if operation:
            report.append(("BLOCK", f"{operation} in progress; resolve it or run git-abort --yes"))
        if conflicts:
            report.append(("BLOCK", f"{len(conflicts)} conflicted file(s): {', '.join(conflicts[:3])}"))
        dirty = self.git("status", "--porcelain", fail=False).splitlines()
        if dirty:
            report.append(("INFO", f"worktree has {len(dirty)} change(s)"))
        hook = self.git("config", "--local", "--get", "core.hooksPath", fail=False)
        if hook != ".githooks":
            if fix:
                self.git("config", "core.hooksPath", ".githooks")
                report.append(("FIXED", "enabled .githooks"))
            else:
                report.append(("WARN", "task commit hook disabled; run doctor --fix"))
        upstream = self.git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", fail=False)
        if branch and not upstream:
            report.append(("WARN", "no upstream; use push PB-NNNN"))
        elif upstream:
            counts = self.git("rev-list", "--left-right", "--count", f"HEAD...{upstream}").split()
            if len(counts) == 2:
                ahead, behind = map(int, counts)
                if ahead and behind: report.append(("BLOCK", f"branch diverged: +{ahead}/-{behind}"))
                elif ahead: report.append(("INFO", f"{ahead} commit(s) ready to push"))
                elif behind: report.append(("WARN", f"behind by {behind}; fetch then merge --ff-only"))
                else: report.append(("OK", f"in sync with {upstream}"))
        remote = self.remote()
        base = str(self.config().get("base", "main"))
        target = f"{remote}/{base}" if remote else base
        if branch and branch != base and self.ref_exists(
                f"refs/remotes/{remote}/{base}" if remote else f"refs/heads/{base}"):
            counts = self.git("rev-list", "--left-right", "--count", f"{target}...HEAD").split()
            if len(counts) == 2:
                target_only, current_only = map(int, counts)
                if not target_only and current_only:
                    report.append(("INFO", f"{target} is {current_only} commit(s) behind current; use promote"))
                elif target_only and current_only:
                    report.append(("BLOCK", f"current and {target} diverged: target +{target_only}, current +{current_only}"))
        match = BRANCH_ID.search(branch)
        if match:
            task_id = match.group(1).upper()
            try:
                task = self.load(task_id)
                if task.get("branch") != branch:
                    if fix:
                        task["branch"] = branch; self.save(task)
                        report.append(("FIXED", f"linked {branch} to {task_id}"))
                    else:
                        report.append(("WARN", f"{task_id} does not record branch; run doctor --fix"))
            except Error:
                report.append(("BLOCK", f"branch names missing task {task_id}"))
        if not report:
            report.append(("OK", "Git state healthy"))
        return report

    def commit(self, task_id: str, message: str, paths: list[str]) -> str:
        task = self.load(task_id)
        if task["state"] not in ("doing", "blocked"):
            raise Error(f"commit needs doing/blocked task, got {task['state']}")
        if self.operation():
            raise Error(f"{self.operation()} in progress")
        if self.git("diff", "--cached", "--name-only"):
            raise Error("index already has staged changes; commit or unstage them first")
        if not paths:
            raise Error("commit needs at least one --path")
        branch = self.git("branch", "--show-current")
        if not branch:
            raise Error("detached HEAD")
        task["branch"] = branch
        self.save(task)
        selected = []
        for value in [*paths, str(self.path(task["id"]).relative_to(self.root))]:
            path = Path(value)
            absolute = path.resolve() if path.is_absolute() else (self.root / path).resolve()
            try:
                selected.append(str(absolute.relative_to(self.root)))
            except ValueError as exc:
                raise Error(f"path outside repository: {value}") from exc
        self.git("add", "--", *dict.fromkeys(selected))
        if not self.git("diff", "--cached", "--name-only"):
            raise Error("nothing to commit")
        self.git("commit", "-m", message, "-m", f"PolyBob-Task: {task['id']}")
        return self.git("rev-parse", "HEAD")

    def push(self, task_id: str, remote: str | None) -> str:
        task = self.load(task_id)
        branch = self.git("branch", "--show-current")
        if not branch:
            raise Error("detached HEAD")
        if task.get("branch") != branch:
            raise Error(f"task branch is {task.get('branch') or 'unset'}, current is {branch}")
        if not self.commits(task["id"]):
            raise Error(f"no commits for {task['id']}")
        remote = remote or self.remote()
        if not remote or remote not in self.git("remote").splitlines():
            raise Error(f"remote not found: {remote}")
        upstream = self.git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", fail=False)
        if upstream:
            self.git("push", remote, branch)
        else:
            self.git("push", "--set-upstream", remote, branch)
        return f"{remote}/{branch}"

    def promote(self, task_id: str, target: str, remote: str | None, apply: bool) -> str | None:
        task = self.load(task_id)
        branch = self.git("branch", "--show-current")
        recorded_branch = task.get("branch")
        if recorded_branch and recorded_branch != branch:
            raise Error("current branch does not belong to task")
        commits = self.commits(task_id)
        if not commits:
            raise Error(f"no commits for {task_id}")
        if any(subprocess.run(
                ["git", "merge-base", "--is-ancestor", commit["sha"], "HEAD"],
                cwd=self.root, check=False, capture_output=True).returncode for commit in commits):
            raise Error("current branch does not contain every task commit")
        if self.git("status", "--porcelain"): raise Error("worktree is not clean")
        remote = remote or self.remote()
        if not remote: raise Error("no remote")
        self.git("fetch", remote, "--prune")
        target_ref = f"{remote}/{target}"
        if not self.ref_exists(f"refs/remotes/{remote}/{target}"):
            raise Error(f"remote target not found: {target_ref}")
        target_only, current_only = map(
            int, self.git("rev-list", "--left-right", "--count", f"{target_ref}...HEAD").split()
        )
        if target_only:
            raise Error(f"not fast-forward: {target_ref} has {target_only} unique commit(s)")
        print(f"promote plan: HEAD -> {target_ref} (+{current_only} commits)")
        if not apply:
            print("dry run; add --yes to apply")
            return None
        self.git("push", remote, f"HEAD:{target}")
        return target_ref

    def abort_git(self) -> str:
        operation = self.operation()
        if not operation:
            raise Error("no merge/rebase/cherry-pick/revert in progress")
        command = {"merge": ("merge", "--abort"), "rebase": ("rebase", "--abort"),
                   "cherry-pick": ("cherry-pick", "--abort"),
                   "revert": ("revert", "--abort")}[operation]
        self.git(*command)
        return operation

    def create(self, args: argparse.Namespace) -> dict:
        task = {
            "id": self.next_id(), "title": args.title.strip(), "state": "todo",
            "p": args.priority, "area": args.area, "why": args.why.strip(),
            "checks": [{"text": value, "done": False} for value in args.check],
            "deps": [value.upper() for value in args.dep], "branch": None,
            "blocked": None, "updated": stamp(),
        }
        self.save(task)
        errors = self.validate_one(task)
        if errors:
            self.path(task["id"]).unlink()
            raise Error("; ".join(errors))
        return task

    def move(self, task_id: str, state: str, reason: str | None = None) -> dict:
        task = self.load(task_id)
        if state not in MOVES.get(task["state"], set()):
            raise Error(f"bad move: {task['state']} -> {state}")
        if state == "doing":
            limit = int(self.config().get("wip", 3))
            active = sum(t["state"] == "doing" for t in self.all() if t["id"] != task["id"])
            if active >= limit:
                raise Error(f"WIP full: {active}/{limit}")
            task["blocked"] = None
        if state == "blocked":
            if not reason:
                raise Error("blocked needs --reason")
            task["blocked"] = reason
        if state == "done":
            self.ready_to_finish(task)
        task["state"] = state
        self.save(task)
        return task

    def ready_to_finish(self, task: dict) -> None:
        if any(not item["done"] for item in task["checks"]):
            raise Error("unfinished checks")
        for dep in task["deps"]:
            if self.load(dep)["state"] != "done":
                raise Error(f"open dependency: {dep}")
        if not self.commits(task["id"]):
            raise Error(f"no Git commit with trailer: PolyBob-Task: {task['id']}")

    def stop(self, task_id: str, reason: str) -> dict:
        task = self.load(task_id)
        if task["state"] not in ("doing", "blocked", "todo"):
            raise Error(f"cannot stop {task['state']} task")
        task["state"] = "dropped"
        task["blocked"] = reason
        self.save(task)
        return task

    def rollback(self, task_id: str, apply: bool) -> dict | None:
        task = self.load(task_id)
        if task["state"] == "dropped":
            raise Error("task is already dropped")
        linked = self.commits(task["id"])
        if not linked:
            raise Error(f"no commits for {task['id']}")
        shas = [item["sha"] for item in linked]
        for sha in shas:
            run = subprocess.run(["git", "merge-base", "--is-ancestor", sha, "HEAD"],
                                 cwd=self.root, check=False)
            if run.returncode:
                raise Error(f"commit is not on current branch: {sha[:8]}")
            if len(self.git("rev-list", "--parents", "-n", "1", sha).split()) > 2:
                raise Error(f"merge commit needs manual rollback: {sha[:8]}")
        print("rollback plan:")
        for item in linked:
            print(f"  {item['sha'][:8]} {item['subject']}")
        if not apply:
            print("dry run; add --yes to apply")
            return None
        if self.git("status", "--porcelain"):
            raise Error("worktree is not clean; commit or stash changes first")
        run = subprocess.run(["git", "revert", "--no-commit", *shas], cwd=self.root,
                             text=True, capture_output=True, check=False)
        if run.returncode:
            subprocess.run(["git", "revert", "--abort"], cwd=self.root,
                           capture_output=True, check=False)
            raise Error(run.stderr.strip() or "git revert failed")
        task["state"] = "dropped"
        task["blocked"] = "rolled back"
        self.save(task)
        self.git("add", "--all")
        self.git("commit", "-m", f"revert({task['id']}): rollback task",
                 "-m", f"PolyBob-Task: {task['id']}")
        return task

    def config(self) -> dict:
        return yaml.safe_load((self.root / "tasks" / "config.yml").read_text())

    def validate_one(self, task: dict) -> list[str]:
        task_id = str(task.get("id", ""))
        errors = []
        if not ID.fullmatch(task_id): errors.append(f"{task_id}: bad id")
        if task.get("state") not in STATES: errors.append(f"{task_id}: bad state")
        if task.get("p") not in PRIORITIES: errors.append(f"{task_id}: bad priority")
        for key in ("title", "area", "why"):
            if not str(task.get(key, "")).strip(): errors.append(f"{task_id}: missing {key}")
        checks = task.get("checks")
        if not isinstance(checks, list) or not checks: errors.append(f"{task_id}: needs checks")
        elif any(not isinstance(x, dict) or not x.get("text") or not isinstance(x.get("done"), bool)
                 for x in checks): errors.append(f"{task_id}: bad checks")
        deps = task.get("deps", [])
        if task_id in deps: errors.append(f"{task_id}: self dependency")
        for dep in deps:
            if not self.path(dep).exists(): errors.append(f"{task_id}: missing {dep}")
        if task.get("state") == "blocked" and not task.get("blocked"):
            errors.append(f"{task_id}: missing blocker")
        if task.get("state") == "done":
            if any(not x["done"] for x in checks): errors.append(f"{task_id}: unchecked done task")
            if not self.commits(task_id): errors.append(f"{task_id}: done without commit")
        return errors

    def validate(self) -> list[str]:
        tasks = self.all()
        errors = [e for task in tasks for e in self.validate_one(task)]
        graph = {task["id"]: task.get("deps", []) for task in tasks}
        visiting, seen = set(), set()

        def walk(node: str) -> None:
            if node in visiting:
                errors.append(f"dependency cycle: {node}"); return
            if node in seen: return
            visiting.add(node)
            for dep in graph.get(node, []): walk(dep)
            visiting.remove(node); seen.add(node)

        for node in graph: walk(node)
        doing = sum(task["state"] == "doing" for task in tasks)
        if doing > int(self.config().get("wip", 3)): errors.append("WIP limit exceeded")
        return errors


def compact(task: dict) -> str:
    done = sum(x["done"] for x in task["checks"])
    flag = {"todo": "○", "doing": "▶", "blocked": "!", "done": "✓", "dropped": "×"}[task["state"]]
    return f"{flag} {task['id']} {task['p']} {done}/{len(task['checks'])} [{task['area']}] {task['title']}"


def show(tasks: DevelopmentControl, task: dict) -> None:
    print(compact(task)); print(task["why"])
    if task["deps"]: print("deps:", " ".join(task["deps"]))
    if task.get("blocked"): print("blocked:", task["blocked"])
    if task.get("branch"): print("branch:", task["branch"])
    for i, item in enumerate(task["checks"], 1):
        print(f"  [{'x' if item['done'] else ' '}] {i} {item['text']}")
    for commit in tasks.commits(task["id"])[:3]:
        print(f"  git {commit['sha'][:8]} {commit['date']} {commit['subject']}")


def board(tasks: DevelopmentControl) -> None:
    rows = tasks.all()
    total = len(rows); done = sum(t["state"] == "done" for t in rows)
    blocked = sum(t["state"] == "blocked" for t in rows)
    pct = round(done / total * 100) if total else 0
    bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
    print(f"PolyBob  {bar} {pct}%  open {total-done}  blocked {blocked}\n")
    for state in STATES:
        group = [t for t in rows if t["state"] == state]
        if not group and state in ("done", "dropped"): continue
        print(f"{state.upper()} {len(group)}")
        for task in sorted(group, key=lambda t: (PRIORITIES.index(t["p"]), t["id"])):
            print(" ", compact(task))
            if task.get("blocked"): print("    ↳", task["blocked"])
        print()


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__); sub = p.add_subparsers(dest="cmd", required=True)
    new = sub.add_parser("new"); new.add_argument("title"); new.add_argument("--why", required=True)
    new.add_argument("--check", action="append", required=True); new.add_argument("--dep", action="append", default=[])
    new.add_argument("-p", "--priority", choices=PRIORITIES, default="P2"); new.add_argument("-a", "--area", required=True)
    sub.add_parser("ls"); sub.add_parser("board"); sub.add_parser("validate")
    one = sub.add_parser("show"); one.add_argument("id")
    mark = sub.add_parser("check"); mark.add_argument("id"); mark.add_argument("number", type=int); mark.add_argument("--undo", action="store_true")
    move = sub.add_parser("move"); move.add_argument("id"); move.add_argument("state", choices=("todo", "doing", "blocked", "done")); move.add_argument("--reason")
    stop = sub.add_parser("stop"); stop.add_argument("id"); stop.add_argument("--reason", required=True)
    rollback = sub.add_parser("rollback"); rollback.add_argument("id"); rollback.add_argument("--yes", action="store_true")
    commit = sub.add_parser("commit"); commit.add_argument("id"); commit.add_argument("-m", "--message", required=True); commit.add_argument("--path", action="append", required=True)
    push = sub.add_parser("push"); push.add_argument("id"); push.add_argument("--remote")
    plan = sub.add_parser("branch-plan"); plan.add_argument("id"); plan.add_argument("--fetch", action="store_true")
    promote = sub.add_parser("promote"); promote.add_argument("id"); promote.add_argument("--to", default="main"); promote.add_argument("--remote"); promote.add_argument("--yes", action="store_true")
    doctor = sub.add_parser("doctor"); doctor.add_argument("--fix", action="store_true"); doctor.add_argument("--fetch", action="store_true")
    abort = sub.add_parser("git-abort"); abort.add_argument("--yes", action="store_true")
    branch = sub.add_parser("branch"); branch.add_argument("id")
    msg = sub.add_parser("validate-message", help=argparse.SUPPRESS); msg.add_argument("file")
    return p


def main() -> int:
    args = parser().parse_args()
    root = Path(os.environ.get("POLYBOB_TASK_ROOT", Path(__file__).resolve().parents[1])).resolve()
    tasks = DevelopmentControl(root)
    try:
        if args.cmd == "new": show(tasks, tasks.create(args))
        elif args.cmd == "ls":
            for task in tasks.all(): print(compact(task))
        elif args.cmd == "board": board(tasks)
        elif args.cmd == "show": show(tasks, tasks.load(args.id))
        elif args.cmd == "check":
            task = tasks.load(args.id); item = args.number - 1
            if item < 0 or item >= len(task["checks"]): raise Error("bad check number")
            task["checks"][item]["done"] = not args.undo; tasks.save(task); show(tasks, task)
        elif args.cmd == "move": show(tasks, tasks.move(args.id, args.state, args.reason))
        elif args.cmd == "stop": show(tasks, tasks.stop(args.id, args.reason))
        elif args.cmd == "rollback":
            task = tasks.rollback(args.id, args.yes)
            if task: show(tasks, task)
        elif args.cmd == "commit": print(tasks.commit(args.id, args.message, args.path)[:12])
        elif args.cmd == "push": print(tasks.push(args.id, args.remote))
        elif args.cmd == "branch-plan":
            action, detail = tasks.branch_plan(args.id, args.fetch); print(f"{action} {detail}")
        elif args.cmd == "promote":
            target = tasks.promote(args.id, args.to, args.remote, args.yes)
            if target: print(target)
        elif args.cmd == "doctor":
            for level, message in tasks.doctor(args.fix, args.fetch): print(f"{level:<5} {message}")
        elif args.cmd == "git-abort":
            if not args.yes: raise Error("git-abort needs --yes")
            print(f"aborted {tasks.abort_git()}")
        elif args.cmd == "branch":
            print(tasks.start_branch(args.id))
        elif args.cmd == "validate-message":
            text = Path(args.file).read_text(); subject = text.splitlines()[0] if text.splitlines() else ""
            if not subject.startswith(("Merge ", "Revert ", "fixup! ", "squash! ")):
                refs = re.findall(r"(?mi)^PolyBob-Task:\s*(PB-\d{4})\s*$", text)
                branch = tasks.git("branch", "--show-current", fail=False); match = BRANCH_ID.search(branch)
                if match and match.group(1).upper() not in refs:
                    raise Error(f"add trailer: PolyBob-Task: {match.group(1).upper()}")
                for ref in refs: tasks.load(ref)
        elif args.cmd == "validate":
            errors = tasks.validate()
            if errors: raise Error("\n".join(errors))
            print(f"OK {len(tasks.all())} tasks")
        return 0
    except Error as exc:
        print(f"ERROR {exc}", file=sys.stderr); return 2


if __name__ == "__main__": raise SystemExit(main())
