"""交易日志 — what you actually did, and what it actually returned.

The north star is "持续提高胜率与收益率". Everything upstream of this file
measures a *research* win rate: 53.2% for the insider edge, 68.4% for the
altcoin short, each from a historical event study. None of it says what
happened when **you** took the trade.

Before this module the loop simply stopped after the intent. There was no fill,
no exit, no realised P&L, and no portfolio ledger — ``get_portfolio_risk_snapshot``
returned ``"not_configured"`` with every field ``None``. Worse, both validated
strategies only ever opened: ``hold_sessions: 20`` and ``hold_days: 5`` lived in
an intent's metadata as strings, and nothing in the repository ever read them
back. A twenty-session edge that never exits is not that edge; it is a permanent
long position wearing its name.

So this is the ledger:

- **One row per position**, from the moment the edge fired to the moment it was
  closed, carrying the planned entry/stop and the actual fills.
- **Slippage attribution**: research said +5.11%; you got something else. The
  gap decomposes into entry slip, exit slip, fees and funding, and each piece is
  stored rather than inferred later.
- **A planned exit date** derived from the edge's own holding period, so the
  horizon is executable data instead of a comment.
- **Manual fills are first class.** This is a personal workbench wired to paper
  execution; the real fills happen in a broker or an exchange the process cannot
  see. A journal that only accepts machine fills would be empty, and an empty
  journal measures nothing.

Nothing here is ever inferred. An unfilled entry has ``actual_entry = None``, and
performance aggregates skip it rather than assuming it filled at the plan.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from libs.db import fact_store

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS journal_entries (
        entry_id TEXT PRIMARY KEY,
        edge_id TEXT NOT NULL,
        symbol TEXT NOT NULL,
        domain TEXT NOT NULL,
        direction TEXT NOT NULL,
        status TEXT NOT NULL,
        intent_id TEXT,
        opened_at TEXT NOT NULL,
        planned_entry REAL,
        planned_stop REAL,
        planned_exit_on TEXT,
        hold_sessions INTEGER,
        qty REAL,
        actual_entry REAL,
        entry_filled_at TEXT,
        actual_exit REAL,
        exit_filled_at TEXT,
        exit_reason TEXT,
        fees REAL NOT NULL DEFAULT 0,
        funding REAL NOT NULL DEFAULT 0,
        realized_pnl REAL,
        realized_pct REAL,
        benchmark_pct REAL,
        research_pct REAL,
        evidence TEXT NOT NULL DEFAULT '',
        note TEXT NOT NULL DEFAULT '',
        meta_json TEXT NOT NULL DEFAULT '{}'
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_journal_edge ON journal_entries(edge_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_journal_open ON journal_entries(status, planned_exit_on)",
)

OPEN_STATUSES = ("planned", "open")


@dataclass
class JournalEntry:
    entry_id: str
    edge_id: str
    symbol: str
    domain: str
    direction: str            # "long" | "short"
    status: str               # planned | open | closed | abandoned
    opened_at: str
    intent_id: str | None = None
    planned_entry: float | None = None
    planned_stop: float | None = None
    planned_exit_on: str | None = None
    hold_sessions: int | None = None
    qty: float | None = None
    actual_entry: float | None = None
    entry_filled_at: str | None = None
    actual_exit: float | None = None
    exit_filled_at: str | None = None
    exit_reason: str | None = None
    fees: float = 0.0
    funding: float = 0.0
    realized_pnl: float | None = None
    realized_pct: float | None = None
    benchmark_pct: float | None = None
    research_pct: float | None = None
    evidence: str = ""
    note: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["is_open"] = self.status in OPEN_STATUSES
        return payload


def _sessions_to_calendar_days(sessions: int) -> int:
    """Trading sessions to calendar days, weekends included.

    Five sessions is a calendar week, not five days. Getting this wrong would
    close a twenty-session position four weekends early.
    """
    return sessions + (sessions // 5) * 2


class TradeJournal:
    """The ledger. One SQLite file, shared with the rest of the fact store."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = db_path
        self._ready = False

    def _connect(self) -> sqlite3.Connection:
        connection = fact_store.connect(self._db_path)
        if not self._ready:
            # Once per process, not once per statement: running five DDLs on
            # every call takes a schema write lock and contends with the audit
            # writer on the same file.
            for statement in _SCHEMA:
                connection.execute(statement)
            connection.commit()
            self._ready = True
        return connection

    # ------------------------------------------------------------------ write
    def open_entry(
        self,
        *,
        edge_id: str,
        symbol: str,
        domain: str,
        direction: str,
        planned_entry: float | None = None,
        planned_stop: float | None = None,
        hold_sessions: int | None = None,
        qty: float | None = None,
        intent_id: str | None = None,
        evidence: str = "",
        research_pct: float | None = None,
        opened_at: datetime | None = None,
        meta: dict[str, Any] | None = None,
    ) -> JournalEntry:
        """Record that an edge fired and a position is planned.

        ``planned_exit_on`` is computed here from the edge's holding period so
        the horizon is a date the closer can act on. It used to be a string in
        an intent's metadata that nothing ever read.
        """
        opened = opened_at or datetime.now(UTC)
        exit_on: str | None = None
        if hold_sessions:
            exit_on = (opened.date() + timedelta(
                days=_sessions_to_calendar_days(int(hold_sessions))
            )).isoformat()

        entry = JournalEntry(
            entry_id=f"jrn_{uuid.uuid4().hex[:10]}",
            edge_id=edge_id, symbol=symbol.upper(), domain=domain,
            direction=direction, status="planned",
            opened_at=opened.isoformat(), intent_id=intent_id,
            planned_entry=planned_entry, planned_stop=planned_stop,
            planned_exit_on=exit_on, hold_sessions=hold_sessions, qty=qty,
            evidence=evidence, research_pct=research_pct, meta=meta or {},
        )
        self._insert(entry)
        return entry

    def record_fill(
        self, entry_id: str, *, price: float, qty: float | None = None,
        fees: float = 0.0, filled_at: datetime | None = None,
    ) -> JournalEntry:
        """The entry actually filled, at this price. Manual entry is expected."""
        entry = self.get(entry_id)
        if entry is None:
            raise KeyError(entry_id)
        entry.actual_entry = float(price)
        entry.entry_filled_at = (filled_at or datetime.now(UTC)).isoformat()
        entry.fees += float(fees)
        if qty is not None:
            entry.qty = float(qty)
        entry.status = "open"
        self._update(entry)
        return entry

    def close_entry(
        self, entry_id: str, *, price: float, reason: str = "horizon",
        fees: float = 0.0, funding: float = 0.0,
        benchmark_pct: float | None = None, closed_at: datetime | None = None,
    ) -> JournalEntry:
        """The position is out. Compute realised P&L from what actually happened.

        Returns are signed by direction, so a short that fell is a gain. Nothing
        is computed unless the entry actually filled — an unfilled plan has no
        return, and inventing one from ``planned_entry`` would quietly grade the
        plan instead of the trade.
        """
        entry = self.get(entry_id)
        if entry is None:
            raise KeyError(entry_id)
        entry.actual_exit = float(price)
        entry.exit_filled_at = (closed_at or datetime.now(UTC)).isoformat()
        entry.exit_reason = reason
        entry.fees += float(fees)
        entry.funding += float(funding)
        entry.benchmark_pct = benchmark_pct
        entry.status = "closed"

        if entry.actual_entry is not None and entry.actual_entry > 0:
            sign = -1.0 if entry.direction == "short" else 1.0
            gross = sign * (entry.actual_exit - entry.actual_entry) / entry.actual_entry
            qty = entry.qty or 0.0
            notional = abs(qty) * entry.actual_entry
            cost_pct = ((entry.fees - entry.funding) / notional) if notional > 0 else 0.0
            entry.realized_pct = round((gross - cost_pct) * 100, 4)
            entry.realized_pnl = round(
                sign * (entry.actual_exit - entry.actual_entry) * abs(qty)
                - entry.fees + entry.funding, 4
            )
        self._update(entry)
        return entry

    def abandon(self, entry_id: str, note: str = "") -> JournalEntry:
        """The plan was never taken. Recorded, not deleted — a skipped signal is data."""
        entry = self.get(entry_id)
        if entry is None:
            raise KeyError(entry_id)
        entry.status = "abandoned"
        entry.note = note or entry.note
        self._update(entry)
        return entry

    # ------------------------------------------------------------------- read
    def get(self, entry_id: str) -> JournalEntry | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM journal_entries WHERE entry_id = ?", (entry_id,)
            ).fetchone()
        return self._from_row(row) if row else None

    def list_entries(
        self, *, edge_id: str | None = None, status: str | None = None, limit: int = 200
    ) -> list[JournalEntry]:
        sql = "SELECT * FROM journal_entries"
        clauses, params = [], []
        if edge_id:
            clauses.append("edge_id = ?")
            params.append(edge_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY opened_at DESC LIMIT ?"
        params.append(int(limit))
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._from_row(row) for row in rows]

    def due_for_exit(self, as_of: date | None = None) -> list[JournalEntry]:
        """Open positions whose validated holding period has elapsed."""
        today = (as_of or datetime.now(UTC).date()).isoformat()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM journal_entries "
                "WHERE status = 'open' AND planned_exit_on IS NOT NULL "
                "AND planned_exit_on <= ? ORDER BY planned_exit_on",
                (today,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def performance(self, edge_id: str | None = None) -> dict[str, Any]:
        """Measured performance per edge, beside the research figure it claims.

        This is the north star made checkable. ``research_pct`` is what the study
        said; ``realized_mean_pct`` is what actually happened; ``slippage_pct``
        is the gap. With fewer than one closed trade every field is ``None`` —
        a win rate over zero trades is not 0%, it is unknown.
        """
        entries = [e for e in self.list_entries(edge_id=edge_id, limit=10_000)
                   if e.status == "closed" and e.realized_pct is not None]
        by_edge: dict[str, list[JournalEntry]] = {}
        for entry in entries:
            by_edge.setdefault(entry.edge_id, []).append(entry)

        out = {}
        for edge, rows in by_edge.items():
            returns = [r.realized_pct for r in rows]
            wins = [r for r in returns if r > 0]
            research = next((r.research_pct for r in rows if r.research_pct is not None), None)
            mean = sum(returns) / len(returns)
            out[edge] = {
                "closed_trades": len(rows),
                "win_rate": round(len(wins) / len(rows), 4),
                "realized_mean_pct": round(mean, 4),
                "research_pct": research,
                # Positive means you did better than the study, negative worse.
                # It is the single number that says whether the edge survives
                # contact with your own execution.
                "slippage_pct": round(mean - research, 4) if research is not None else None,
                "total_fees": round(sum(r.fees for r in rows), 4),
                "total_funding": round(sum(r.funding for r in rows), 4),
                "open_positions": len([
                    e for e in self.list_entries(edge_id=edge, limit=10_000)
                    if e.status in OPEN_STATUSES
                ]),
            }
        return out

    # -------------------------------------------------------------- internals
    def _insert(self, entry: JournalEntry) -> None:
        payload = asdict(entry)
        payload["meta_json"] = json.dumps(payload.pop("meta"), ensure_ascii=False)
        columns = ", ".join(payload)
        placeholders = ", ".join("?" for _ in payload)
        with self._connect() as connection:
            connection.execute(
                f"INSERT INTO journal_entries ({columns}) VALUES ({placeholders})",
                list(payload.values()),
            )
            connection.commit()

    def _update(self, entry: JournalEntry) -> None:
        payload = asdict(entry)
        payload["meta_json"] = json.dumps(payload.pop("meta"), ensure_ascii=False)
        entry_id = payload.pop("entry_id")
        assignments = ", ".join(f"{k} = ?" for k in payload)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE journal_entries SET {assignments} WHERE entry_id = ?",
                [*payload.values(), entry_id],
            )
            connection.commit()

    @staticmethod
    def _from_row(row: sqlite3.Row) -> JournalEntry:
        data = dict(row)
        meta = data.pop("meta_json", "{}")
        try:
            data["meta"] = json.loads(meta)
        except (TypeError, ValueError):
            data["meta"] = {}
        return JournalEntry(**data)


_journal: TradeJournal | None = None


def get_journal() -> TradeJournal:
    global _journal
    if _journal is None:
        _journal = TradeJournal()
    return _journal


__all__ = ["JournalEntry", "OPEN_STATUSES", "TradeJournal", "get_journal"]
