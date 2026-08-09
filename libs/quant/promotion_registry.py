"""Promotion registry: the authoritative lab-vs-promoted gate for the desk.

``scripts/event_study_board.py`` — the single writer — regenerates
``data/promotion_board.json`` from the committed experiment output. This module
loads it and answers the only question the execution desk cares about: *is this
strategy allowed to open a position on this instrument?* Anything not explicitly
gate-approved **for trading** stays in ``lab``.

Two things this gate refuses to conflate:

- **Approved is not tradable.** A board row carries a ``role``. ``trade`` means a
  position may be opened. ``avoid`` means the study found a reliable *negative*
  drift that cannot be shorted in that market — a filter that stops you buying,
  earning nothing. Both are real findings; only the first is permission. An
  earlier board listed two avoidance filters as approved edges alongside one
  genuine long signal, which made the desk look three edges deep when it was
  one.
- **Unlabelled is not trusted.** A row without an explicit role gets no
  permission. The failure mode this file exists to prevent is a hand-written row
  reaching the execution desk, so an unrecognised role fails closed like a
  missing board does.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DEFAULT_BOARD_PATH = Path("data/promotion_board.json")

ROLE_TRADE = "trade"
ROLE_AVOID = "avoid"


@dataclass(frozen=True)
class PromotionRecord:
    strategy: str
    instrument: str
    approved: bool
    role: str                       # "trade" | "avoid" | "" when unlabelled
    sharpe: float
    dsr: float | None
    failed: list[str]
    domain: str = ""
    win_rate: float | None = None
    mean_excess_pct: float | None = None
    t_stat: float | None = None            # cluster-robust; the board recomputes it
    t_stat_iid: float | None = None        # the old, invalid figure — kept to show the gap
    t_hurdle: float | None = None
    n: int | None = None
    n_clusters: int | None = None          # independent units; the real sample size
    cluster_by: str = ""
    wild_p: float | None = None          # correctly sized at small G
    p_floor: float | None = None         # finest p this many clusters can express
    resolvable: bool | None = None       # can this sample express significance at all?
    evidence_end: str | None = None        # last event observed, not last script run
    max_evidence_age_days: int | None = None
    implementation: str = ""
    evidence: str = ""
    source: str = ""

    @property
    def evidence_age_days(self) -> int | None:
        """How stale this row's evidence is *right now*.

        Computed rather than stored. The board is a file that must rebuild to the
        same bytes from the same evidence, so it cannot hold a number that changes
        every midnight — but the process asking for permission can work it out.
        """
        if not self.evidence_end:
            return None
        try:
            end = dt.date.fromisoformat(self.evidence_end[:10])
        except ValueError:
            return None
        return (dt.datetime.now(dt.UTC).date() - end).days

    @property
    def evidence_expired(self) -> bool:
        """True when nobody has re-measured this edge inside its declared shelf life.

        An edge is a claim about how a market behaves, and markets change. Without
        this, a finding kept its trade permission for as long as the file sat on
        disk and would have gone on granting it long after the effect died.
        """
        age, limit = self.evidence_age_days, self.max_evidence_age_days
        if age is None or not limit:
            return False
        return age > limit

    def to_dict(self) -> dict[str, Any]:
        """Serialise for the API, *including* the computed fields.

        ``dataclasses.asdict`` only walks declared fields, so the age and the
        expiry verdict — both properties, because both depend on today's date —
        would silently vanish from the payload and reach the dashboard as
        ``undefined``. Anything the frontend reads has to be named here.
        """
        payload = asdict(self)
        payload["evidence_age_days"] = self.evidence_age_days
        payload["evidence_expired"] = self.evidence_expired
        payload["tradable"] = self.tradable
        return payload

    @property
    def tradable(self) -> bool:
        """Approved, labelled tradable, *and* still inside its shelf life."""
        return self.approved and self.role == ROLE_TRADE and not self.evidence_expired

    @property
    def is_avoid_filter(self) -> bool:
        # An avoidance filter expires too: "these 257 A-shares fell last quarter"
        # is not a reason to skip them today if nobody has looked since.
        return self.approved and self.role == ROLE_AVOID and not self.evidence_expired


class PromotionRegistry:
    def __init__(self, board_path: str | Path | None = None) -> None:
        self.board_path = Path(board_path) if board_path else DEFAULT_BOARD_PATH
        self._records: list[PromotionRecord] = []
        self.loaded_at: str | None = None
        self.meta: dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        self._records = []
        self.meta = {}
        try:
            data = json.loads(self.board_path.read_text())
        except Exception:
            return  # fail-closed: no board => nothing promoted
        self.meta = {k: v for k, v in data.items() if k != "board"}
        for row in data.get("board", []):
            self._records.append(
                PromotionRecord(
                    strategy=str(row.get("strategy", "")),
                    instrument=str(row.get("instrument", "")),
                    approved=bool(row.get("approved", False)),
                    role=str(row.get("role", "")),
                    # Event-study edges (insider clusters, dragon-tiger) report a
                    # mean excess return and t-stat rather than a Sharpe, so a
                    # missing value is normal and must not break the registry.
                    sharpe=float(row.get("sharpe") or 0.0),
                    dsr=row.get("dsr"),
                    failed=list(row.get("failed", [])),
                    domain=str(row.get("domain", "")),
                    win_rate=row.get("win_rate"),
                    mean_excess_pct=row.get("mean_excess_pct"),
                    t_stat=row.get("t_stat"),
                    t_stat_iid=row.get("t_stat_iid"),
                    t_hurdle=row.get("t_hurdle"),
                    n=row.get("n"),
                    n_clusters=row.get("n_clusters"),
                    cluster_by=str(row.get("cluster_by", "")),
                    wild_p=row.get("wild_p"),
                    p_floor=row.get("p_floor"),
                    resolvable=row.get("resolvable"),
                    evidence_end=row.get("evidence_end"),
                    max_evidence_age_days=row.get("max_evidence_age_days"),
                    implementation=str(row.get("implementation", "")),
                    evidence=str(row.get("evidence", "")),
                    source=str(row.get("source", "")),
                )
            )
        self.loaded_at = str(data.get("generated_at") or self.board_path.stat().st_mtime)

    def is_promoted(self, strategy: str, instrument: str | None = None) -> bool:
        """True only if a gate-approved **tradable** record exists.

        With ``instrument`` given, requires that exact pair. Without it, the
        strategy is promoted if it cleared the gate on *any* instrument. An
        approved ``avoid`` filter never grants permission: it is a reason not to
        buy, not a position.
        """
        for r in self._records:
            if r.strategy != strategy or not r.tradable:
                continue
            if instrument is None or r.instrument == instrument:
                return True
        return False

    def promoted_pairs(self) -> list[PromotionRecord]:
        """Records that grant trade permission."""
        return [r for r in self._records if r.tradable]

    def demoted_pairs(self) -> list[PromotionRecord]:
        """Rows that were tested and did not clear the gate.

        Surfaced deliberately. A desk with nothing to trade should say *why* it
        has nothing to trade, otherwise an empty screen reads as a broken feed and
        invites someone to go trade on a hunch instead. These rows are the answer:
        the edges exist as findings, they are simply not significant once their
        events are treated as the dependent observations they are.
        """
        return [r for r in self._records if not r.approved]

    def avoid_filters(self, domain: str | None = None) -> list[PromotionRecord]:
        """Approved negative-drift findings — real, but never a position."""
        out = [r for r in self._records if r.is_avoid_filter]
        if domain is None:
            return out
        return [r for r in out if r.domain == domain]

    def records(self) -> list[PromotionRecord]:
        return list(self._records)

    def reason_blocked(self, strategy: str, instrument: str | None = None) -> str:
        recs = [r for r in self._records if r.strategy == strategy
                and (instrument is None or r.instrument == instrument)]
        if not recs:
            return "no backtest record — strategy未经真实历史回测，留 lab"
        if any(r.tradable for r in recs):
            return "promoted"
        if any(r.is_avoid_filter for r in recs):
            return ("该边只是回避过滤器(role=avoid)：市场上无法做空这个负漂移，"
                    "它能阻止你买入，但不构成开仓依据")
        unlabelled = [r for r in recs if r.approved and r.role not in (ROLE_TRADE, ROLE_AVOID)]
        if unlabelled:
            return "board 行缺少 role 标签，按 fail-closed 不授予开仓权限"
        # Expiry is checked before the gate failures: a row that cleared every
        # statistical bar and then went stale needs a different answer from one
        # that never cleared them, because the action it implies is different —
        # re-run the experiment, rather than abandon the hypothesis.
        expired = [r for r in recs if r.approved and r.evidence_expired]
        if expired:
            r = expired[0]
            return (f"证据已过期:最后一个事件在 {r.evidence_end},距今 {r.evidence_age_days} 天,"
                    f"超过声明的 {r.max_evidence_age_days} 天保质期。重跑该实验以恢复权限。")
        failed = sorted({f for r in recs for f in r.failed})
        return f"未过门禁: {', '.join(failed)}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "board_path": str(self.board_path),
            "generated_at": self.loaded_at,
            "n_trials": self.meta.get("n_trials"),
            "t_hurdle": self.meta.get("t_hurdle"),
            "total": len(self._records),
            "promoted": [f"{r.strategy}@{r.instrument}" for r in self.promoted_pairs()],
            "avoid_filters": [f"{r.strategy}@{r.instrument}" for r in self.avoid_filters()],
        }


_default_registry: PromotionRegistry | None = None


def get_registry() -> PromotionRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = PromotionRegistry()
    return _default_registry


def is_promoted(strategy: str, instrument: str | None = None) -> bool:
    return get_registry().is_promoted(strategy, instrument)


__all__ = [
    "ROLE_AVOID",
    "ROLE_TRADE",
    "PromotionRecord",
    "PromotionRegistry",
    "get_registry",
    "is_promoted",
]
