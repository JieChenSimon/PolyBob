"""Read-only Development Control projection for the dashboard."""

from __future__ import annotations

import re
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import yaml
from fastapi import APIRouter

router = APIRouter()
ROOT = Path(__file__).resolve().parents[2]
ITEMS = ROOT / "tasks" / "items"
TRAILER = re.compile(r"(?mi)^PolyBob-Task:\s*(PB-\d{4})\s*$")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True,
                          check=False).stdout.strip()


def _contains(ref: str, sha: str) -> bool:
    return subprocess.run(["git", "merge-base", "--is-ancestor", sha, ref], cwd=ROOT,
                          capture_output=True, check=False).returncode == 0


def _commits() -> dict[str, list[dict[str, str]]]:
    run = subprocess.run(
        ["git", "log", "--all", "--format=%x1e%H%x1f%ad%x1f%s%x1f%b", "--date=short", "-n", "300"],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    by_task: dict[str, list[dict[str, str]]] = {}
    for record in run.stdout.split("\x1e"):
        parts = record.strip().split("\x1f", 3)
        if len(parts) != 4:
            continue
        sha, date, subject, body = parts
        for task_id in TRAILER.findall(body):
            by_task.setdefault(task_id, []).append({"sha": sha, "date": date, "subject": subject})
    return by_task


def _delivery(task: dict, commits: list[dict[str, str]]) -> str:
    if not commits:
        return "uncommitted"
    remote = _git("config", "--get", "branch.main.remote")
    if not remote or remote == ".":
        remotes = _git("remote").splitlines()
        remote = remotes[0] if remotes else ""
    main_ref = f"{remote}/main" if remote else "main"
    if _git("rev-parse", "--verify", main_ref) and all(
            _contains(main_ref, item["sha"]) for item in commits):
        return "main"
    branch = task.get("branch")
    branch_ref = f"{remote}/{branch}" if remote and branch else ""
    if branch_ref and _git("rev-parse", "--verify", branch_ref) and all(
            _contains(branch_ref, item["sha"]) for item in commits):
        return "pushed"
    return "local"


@router.get("/api/dev-control")
async def control_state():
    commits = _commits()
    tasks = []
    for path in sorted(ITEMS.glob("PB-*.yml")) if ITEMS.exists() else []:
        task = yaml.safe_load(path.read_text())
        task_commits = commits.get(task["id"], [])
        task["delivery"] = _delivery(task, task_commits)
        task["commits"] = [dict(item, sha=item["sha"][:8]) for item in task_commits]
        task["progress"] = {
            "done": sum(bool(item["done"]) for item in task["checks"]),
            "total": len(task["checks"]),
        }
        tasks.append(task)
    counts = Counter(task["state"] for task in tasks)
    measurable = len(tasks) - counts["dropped"]
    return {
        "tasks": tasks,
        "counts": {state: counts[state] for state in ("todo", "doing", "blocked", "done", "dropped")},
        "completion_pct": round(counts["done"] / measurable * 100) if measurable else 0,
        "updated": datetime.now(UTC).isoformat(),
    }
