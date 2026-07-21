"""Lightweight, local experiment registry for reproducible research.

Most quant workflows decay into a mess of notebooks and one-off scripts where a
backtest's result cannot be reconstructed: which data version, which
parameters, which code produced this Sharpe? The professional answer is
experiment tracking (MLflow and friends) so every run logs its inputs and
outputs and can be compared and reproduced.

This is a dependency-free, server-free equivalent backed by the project's
sqlite store. Each run records its parameters, metrics, and the *versions* that
make it reproducible — data version, model version, and code (git) version — so
a conclusion can always be traced back to exactly what produced it, satisfying
the roadmap's "Traceable output" gate.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _git_sha(cwd: str | Path | None = None) -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    experiment: str
    created_at: datetime
    params: dict[str, Any]
    metrics: dict[str, float]
    data_version: str | None
    model_version: str | None
    code_version: str | None
    tags: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "experiment": self.experiment,
            "created_at": self.created_at.isoformat(),
            "params": self.params,
            "metrics": self.metrics,
            "data_version": self.data_version,
            "model_version": self.model_version,
            "code_version": self.code_version,
            "tags": self.tags,
            "notes": self.notes,
        }


class ExperimentRegistry:
    """Append-only registry of research/backtest runs."""

    def __init__(self, db_path: str | Path, *, capture_git: bool = True) -> None:
        self.db_path = str(db_path)
        self._capture_git = capture_git
        self._init()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS experiment_runs (
                    run_id TEXT PRIMARY KEY,
                    experiment TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    data_version TEXT,
                    model_version TEXT,
                    code_version TEXT,
                    tags_json TEXT NOT NULL,
                    notes TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_experiment_runs_experiment "
                "ON experiment_runs(experiment, created_at)"
            )

    def log_run(
        self,
        experiment: str,
        *,
        params: dict[str, Any] | None = None,
        metrics: dict[str, float] | None = None,
        data_version: str | None = None,
        model_version: str | None = None,
        code_version: str | None = None,
        tags: list[str] | None = None,
        notes: str = "",
        run_id: str | None = None,
    ) -> RunRecord:
        record = RunRecord(
            run_id=run_id or uuid.uuid4().hex,
            experiment=experiment,
            created_at=datetime.now(UTC),
            params=dict(params or {}),
            metrics={k: float(v) for k, v in (metrics or {}).items()},
            data_version=data_version,
            model_version=model_version,
            code_version=code_version if code_version is not None else (_git_sha() if self._capture_git else None),
            tags=list(tags or []),
            notes=notes,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO experiment_runs (
                    run_id, experiment, created_at, params_json, metrics_json,
                    data_version, model_version, code_version, tags_json, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.run_id,
                    record.experiment,
                    record.created_at.isoformat(),
                    json.dumps(record.params, ensure_ascii=False, sort_keys=True),
                    json.dumps(record.metrics, ensure_ascii=False, sort_keys=True),
                    record.data_version,
                    record.model_version,
                    record.code_version,
                    json.dumps(record.tags, ensure_ascii=False),
                    record.notes,
                ),
            )
        return record

    def get_run(self, run_id: str) -> RunRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM experiment_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return self._row_to_record(row) if row else None

    def list_runs(self, experiment: str | None = None, *, limit: int = 100) -> list[RunRecord]:
        query = "SELECT * FROM experiment_runs"
        params: list[Any] = []
        if experiment:
            query += " WHERE experiment = ?"
            params.append(experiment)
        query += " ORDER BY created_at DESC, run_id DESC LIMIT ?"
        params.append(max(1, min(limit, 1000)))
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._row_to_record(row) for row in rows]

    def best_run(
        self,
        metric: str,
        *,
        experiment: str | None = None,
        maximize: bool = True,
    ) -> RunRecord | None:
        candidates = [r for r in self.list_runs(experiment, limit=1000) if metric in r.metrics]
        if not candidates:
            return None
        return (max if maximize else min)(candidates, key=lambda r: r.metrics[metric])

    def _row_to_record(self, row: sqlite3.Row) -> RunRecord:
        return RunRecord(
            run_id=row["run_id"],
            experiment=row["experiment"],
            created_at=datetime.fromisoformat(row["created_at"]),
            params=json.loads(row["params_json"]),
            metrics=json.loads(row["metrics_json"]),
            data_version=row["data_version"],
            model_version=row["model_version"],
            code_version=row["code_version"],
            tags=json.loads(row["tags_json"]),
            notes=row["notes"],
        )


__all__ = ["ExperimentRegistry", "RunRecord"]
