"""Data-quality gate: block or downgrade conclusions on bad input.

A quant conclusion is only as trustworthy as the data behind it. The
productionization roadmap's "Real input" and "Failure behavior" gates require
that stale, incomplete, or malformed data *explicitly* blocks or downgrades a
conclusion rather than silently poisoning it. This module makes that policy a
reusable, testable object instead of scattered ad-hoc checks.

Three independent checks feed one verdict:

- **Freshness** — how old is the data versus when it was produced? Beyond a
  warn threshold the conclusion is downgraded; beyond a block threshold it is
  refused.
- **Completeness** — are all required fields present and non-null?
- **Schema** — do present fields have the expected type and finite value?

The combined :class:`DataQualityReport` carries a ``verdict`` of ``ok`` /
``degraded`` / ``blocked`` plus the specific reasons, so callers can decide
whether to act, act-with-caveat, or refuse.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Iterable, Mapping


class Verdict(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    BLOCKED = "blocked"

    @property
    def rank(self) -> int:
        return {"ok": 0, "degraded": 1, "blocked": 2}[self.value]


def worst(verdicts: Iterable[Verdict]) -> Verdict:
    result = Verdict.OK
    for verdict in verdicts:
        if verdict.rank > result.rank:
            result = verdict
    return result


@dataclass(frozen=True)
class FreshnessPolicy:
    """Thresholds for how stale data may be before it degrades/blocks."""

    warn_after: timedelta
    block_after: timedelta

    def __post_init__(self) -> None:
        if self.block_after < self.warn_after:
            raise ValueError("block_after must be >= warn_after")


@dataclass(frozen=True)
class CheckResult:
    name: str
    verdict: Verdict
    detail: str


@dataclass(frozen=True)
class DataQualityReport:
    verdict: Verdict
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.verdict is Verdict.OK

    @property
    def blocked(self) -> bool:
        return self.verdict is Verdict.BLOCKED

    @property
    def reasons(self) -> list[str]:
        return [c.detail for c in self.checks if c.verdict is not Verdict.OK]

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "checks": [
                {"name": c.name, "verdict": c.verdict.value, "detail": c.detail}
                for c in self.checks
            ],
        }


def check_freshness(
    source_time: datetime | None,
    now: datetime,
    policy: FreshnessPolicy,
    *,
    label: str = "freshness",
) -> CheckResult:
    if source_time is None:
        return CheckResult(label, Verdict.BLOCKED, "no source timestamp")
    age = now - source_time
    if age < timedelta(0):
        # Source time in the future — clock skew or a look-ahead bug upstream.
        return CheckResult(label, Verdict.BLOCKED, f"source timestamp is in the future by {(-age)}")
    if age >= policy.block_after:
        return CheckResult(label, Verdict.BLOCKED, f"data is {age} old (>= block {policy.block_after})")
    if age >= policy.warn_after:
        return CheckResult(label, Verdict.DEGRADED, f"data is {age} old (>= warn {policy.warn_after})")
    return CheckResult(label, Verdict.OK, f"data is {age} old")


def check_completeness(
    record: Mapping[str, Any],
    required_fields: Iterable[str],
    *,
    label: str = "completeness",
) -> CheckResult:
    missing = [f for f in required_fields if record.get(f) is None]
    if missing:
        return CheckResult(label, Verdict.BLOCKED, f"missing required fields: {', '.join(missing)}")
    return CheckResult(label, Verdict.OK, "all required fields present")


def check_schema(
    record: Mapping[str, Any],
    schema: Mapping[str, type | tuple[type, ...]],
    *,
    label: str = "schema",
    require_finite: bool = True,
) -> CheckResult:
    problems: list[str] = []
    for field_name, expected in schema.items():
        if field_name not in record or record[field_name] is None:
            continue  # completeness owns missing/null
        value = record[field_name]
        if isinstance(value, bool) and expected not in (bool,) and not (
            isinstance(expected, tuple) and bool in expected
        ):
            # Guard against bool sneaking in as int (bool is a subclass of int).
            problems.append(f"{field_name} is bool, expected {expected}")
            continue
        if not isinstance(value, expected):
            problems.append(f"{field_name} is {type(value).__name__}, expected {expected}")
            continue
        if require_finite and isinstance(value, float) and not math.isfinite(value):
            problems.append(f"{field_name} is non-finite ({value})")
    if problems:
        return CheckResult(label, Verdict.BLOCKED, "; ".join(problems))
    return CheckResult(label, Verdict.OK, "schema valid")


def validate_record(
    record: Mapping[str, Any],
    *,
    now: datetime,
    source_time_field: str | None = None,
    freshness: FreshnessPolicy | None = None,
    required_fields: Iterable[str] = (),
    schema: Mapping[str, type | tuple[type, ...]] | None = None,
) -> DataQualityReport:
    """Run all configured checks over one record and combine into a verdict."""
    checks: list[CheckResult] = []

    if freshness is not None:
        source_time = None
        if source_time_field is not None:
            raw = record.get(source_time_field)
            source_time = _coerce_datetime(raw)
        checks.append(check_freshness(source_time, now, freshness))

    if required_fields:
        checks.append(check_completeness(record, required_fields))

    if schema:
        checks.append(check_schema(record, schema))

    verdict = worst(c.verdict for c in checks) if checks else Verdict.OK
    return DataQualityReport(verdict=verdict, checks=checks)


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


__all__ = [
    "CheckResult",
    "DataQualityReport",
    "FreshnessPolicy",
    "Verdict",
    "check_completeness",
    "check_freshness",
    "check_schema",
    "validate_record",
    "worst",
]
