"""Promotion registry: the authoritative lab-vs-promoted gate for the desk.

The promotion backtest (``scripts/promotion_backtest.py``) writes a board of
(strategy, instrument) verdicts to ``data/promotion_board.json``. This module
loads it and answers the only question the execution desk cares about: *is this
strategy allowed to trade this instrument live?* Anything not explicitly
gate-approved stays in ``lab``.

Fail-closed: if the board is missing or unreadable, nothing is promoted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_BOARD_PATH = Path("data/promotion_board.json")


@dataclass(frozen=True)
class PromotionRecord:
    strategy: str
    instrument: str
    approved: bool
    sharpe: float
    dsr: float | None
    failed: list[str]


class PromotionRegistry:
    def __init__(self, board_path: str | Path | None = None) -> None:
        self.board_path = Path(board_path) if board_path else DEFAULT_BOARD_PATH
        self._records: list[PromotionRecord] = []
        self.loaded_at: str | None = None
        self.reload()

    def reload(self) -> None:
        self._records = []
        try:
            data = json.loads(self.board_path.read_text())
        except Exception:
            return  # fail-closed: no board => nothing promoted
        for row in data.get("board", []):
            self._records.append(
                PromotionRecord(
                    strategy=str(row.get("strategy", "")),
                    instrument=str(row.get("instrument", "")),
                    approved=bool(row.get("approved", False)),
                    sharpe=float(row.get("sharpe", 0.0)),
                    dsr=row.get("dsr"),
                    failed=list(row.get("failed", [])),
                )
            )
        self.loaded_at = str(data.get("generated_at") or self.board_path.stat().st_mtime)

    def is_promoted(self, strategy: str, instrument: str | None = None) -> bool:
        """True only if a gate-approved record exists for this strategy.

        With ``instrument`` given, requires that exact pair approved. Without it,
        the strategy is promoted if it cleared the gate on *any* instrument.
        """
        for r in self._records:
            if r.strategy != strategy or not r.approved:
                continue
            if instrument is None or r.instrument == instrument:
                return True
        return False

    def promoted_pairs(self) -> list[PromotionRecord]:
        return [r for r in self._records if r.approved]

    def reason_blocked(self, strategy: str, instrument: str | None = None) -> str:
        recs = [r for r in self._records if r.strategy == strategy
                and (instrument is None or r.instrument == instrument)]
        if not recs:
            return "no backtest record — strategy未经真实历史回测，留 lab"
        if any(r.approved for r in recs):
            return "promoted"
        failed = sorted({f for r in recs for f in r.failed})
        return f"未过门禁: {', '.join(failed)}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "board_path": str(self.board_path),
            "total": len(self._records),
            "promoted": [f"{r.strategy}@{r.instrument}" for r in self.promoted_pairs()],
        }


_default_registry: PromotionRegistry | None = None


def get_registry() -> PromotionRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = PromotionRegistry()
    return _default_registry


def is_promoted(strategy: str, instrument: str | None = None) -> bool:
    return get_registry().is_promoted(strategy, instrument)


__all__ = ["PromotionRecord", "PromotionRegistry", "get_registry", "is_promoted"]
