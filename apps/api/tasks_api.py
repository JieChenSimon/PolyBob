"""Read-only projection of the Git-native task files for the dashboard."""

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
            by_task.setdefault(task_id, []).append(
                {"sha": sha[:8], "date": date, "subject": subject}
            )
    return by_task


@router.get("/api/tasks")
async def task_board():
    commits = _commits()
    tasks = []
    for path in sorted(ITEMS.glob("PB-*.yml")) if ITEMS.exists() else []:
        task = yaml.safe_load(path.read_text())
        task["commits"] = commits.get(task["id"], [])
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
