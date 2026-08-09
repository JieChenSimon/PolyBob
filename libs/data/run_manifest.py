"""The record of what an experiment actually ran against.

An experiment's result is only evidence if someone can get the same number back.
This project's could not: re-running the insider study gave n=753, then n=667,
because the inputs were an overwritable cache with no timestamps. The statistics
above that were careful — pre-registered hypotheses, clustered standard errors, a
multiple-testing hurdle — and all of it rested on a sample that moved.

A manifest pins the three things that decide a result:

1. **``as_of``** — the observation cut. Every read goes through
   :func:`libs.data.store.read` with this value, so the run sees the data as it
   stood at one instant and not a minute later.
2. **The code** — git commit, and whether the tree was dirty. A result from
   uncommitted code is not reproducible and says so.
3. **The parameters** — hold period, costs, universe, thresholds. The things that
   would otherwise be literals somebody edited between runs.

Written next to the evidence, so ``data/insider_results.json`` and its manifest
travel together and the board can refuse a result whose manifest is missing.

    manifest = pin("insider_cluster_buy", params={"hold_days": 20, "cost_bps": 10})
    bars = store.read(store.DAILY_BARS, symbols, as_of=manifest.as_of)
    ...
    manifest.save("data/insider_results.json")
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MANIFEST_SUFFIX = ".manifest.json"


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=10, check=False
        )
        return out.stdout.strip() or None if out.returncode == 0 else None
    except Exception:  # noqa: BLE001 — no git is a fact to record, not a crash
        return None


# What counts as "code" for reproducibility. A manifest asks one question: does the
# recorded commit describe the logic that ran? Data files do not answer it — and
# including them made the check self-defeating, because an experiment writes its own
# result and manifest, so the *next* run would see those as changes and declare
# itself unreproducible forever.
_CODE_DIRS = ("libs/", "modules/", "apps/", "scripts/", "strategies/")
_CODE_FILES = ("pyproject.toml", "pytest.ini")


def _is_code(path: str) -> bool:
    return path.startswith(_CODE_DIRS) or path in _CODE_FILES


def _code_state() -> dict[str, Any]:
    """Whether the recorded commit describes the code that ran.

    Only **tracked source modifications** count. Untracked files are excluded
    deliberately: a fresh result file is not a change to the logic, and treating it
    as one would mean the first run poisons every run after it.

    An untracked *source* file is a real gap — the run may import it — so those are
    counted, and only the ``??`` status of non-code paths is ignored.
    """
    commit = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain") or ""
    dirty: list[str] = []
    for line in status.splitlines():
        if len(line) < 4:
            continue
        code_flag, path = line[:2], line[3:].strip().strip('"')
        # Renames read "old -> new"; the destination is what matters.
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if code_flag == "??" and not _is_code(path):
            continue          # a new data/scratch file is not a code change
        if _is_code(path):
            dirty.append(path)
    return {
        "commit": commit,
        "dirty": bool(dirty),
        "dirty_files": len(dirty),
        # Named, not just counted: "638 changes" is unactionable, and the first few
        # paths usually say immediately whether the run should be trusted.
        "dirty_sample": sorted(dirty)[:8],
    }


@dataclass
class RunManifest:
    """Everything needed to run this experiment again and get the same answer."""

    experiment: str
    as_of: dt.datetime
    params: dict[str, Any] = field(default_factory=dict)
    code: dict[str, Any] = field(default_factory=_code_state)
    started_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))
    inputs: dict[str, Any] = field(default_factory=dict)

    def record_input(self, dataset: str, **facts: Any) -> None:
        """Note what a dataset supplied — row counts, date span, symbols seen.

        Not decoration. If a re-run produces a different n, this is what tells you
        whether the data moved or the code did, which are two very different
        problems and were indistinguishable before.
        """
        self.inputs[dataset] = facts

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment": self.experiment,
            "as_of": self.as_of.isoformat(),
            "params": self.params,
            "code": self.code,
            "started_at": self.started_at.isoformat(),
            "inputs": self.inputs,
            "reproducible": self.reproducible,
        }

    @property
    def reproducible(self) -> bool:
        """Whether this run could be replayed byte-for-byte by someone else."""
        return bool(self.code.get("commit")) and not self.code.get("dirty")

    def save(self, beside: str | Path) -> Path:
        """Write next to the result file it describes."""
        path = Path(str(beside)).with_suffix("")
        out = path.parent / f"{path.name}{MANIFEST_SUFFIX}"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n")
        return out

    def warn_lines(self) -> list[str]:
        """Human-readable caveats to print at the end of a run."""
        out: list[str] = []
        if not self.code.get("commit"):
            out.append("没有 git commit —— 这次运行无法被别人复现。")
        elif self.code.get("dirty"):
            sample = ", ".join(self.code.get("dirty_sample") or [])
            out.append(
                f"有 {self.code['dirty_files']} 个源码文件未提交 —— "
                f"commit {self.code['commit'][:8]} 并不描述实际跑的代码,"
                f"这个结果不能授予开仓权限。先提交,再重跑。"
                + (f" ({sample}…)" if sample else "")
            )
        return out


def pin(
    experiment: str,
    *,
    as_of: dt.datetime | None = None,
    params: dict[str, Any] | None = None,
) -> RunManifest:
    """Open a manifest and fix the observation cut for the whole run.

    Call this **before** the first read. Taking ``as_of`` at the start rather than
    per-read is the point: otherwise a long run straddles a data refresh and its
    early and late reads disagree about what was known, which is a subtle
    look-ahead that no test would catch.
    """
    return RunManifest(
        experiment=experiment,
        as_of=as_of or dt.datetime.now(dt.UTC),
        params=dict(params or {}),
    )


def load(beside: str | Path) -> RunManifest | None:
    """Read the manifest for a result file, or ``None`` if it has none.

    ``None`` is meaningful: a result with no manifest predates this discipline and
    cannot be replayed. Callers should treat it as unverifiable rather than
    assuming it was fine.
    """
    path = Path(str(beside)).with_suffix("")
    out = path.parent / f"{path.name}{MANIFEST_SUFFIX}"
    if not out.exists():
        return None
    try:
        raw = json.loads(out.read_text())
    except Exception:  # noqa: BLE001
        return None
    return RunManifest(
        experiment=str(raw.get("experiment", "")),
        as_of=dt.datetime.fromisoformat(raw["as_of"]),
        params=dict(raw.get("params") or {}),
        code=dict(raw.get("code") or {}),
        started_at=dt.datetime.fromisoformat(
            raw.get("started_at") or raw["as_of"]
        ),
        inputs=dict(raw.get("inputs") or {}),
    )


__all__ = ["MANIFEST_SUFFIX", "RunManifest", "load", "pin"]
