"""Point-in-time, survivorship-free instrument universe.

Survivorship bias is a foundational data-integrity error: if a backtest's
universe contains only instruments that still exist today, it silently excludes
everything that was delisted, resolved, merged, or went to zero — and
systematically overstates performance. This is acute for PolyBob's markets:
Polymarket questions *resolve and disappear*, and crypto tokens delist
constantly, so "today's tradable markets" is a heavily survivor-selected set.

:class:`PointInTimeUniverse` fixes this by recording each member's active
lifespan (``listed_at`` → ``delisted_at``). ``active_as_of(t)`` returns exactly
the instruments a trader could have traded at ``t`` — including ones long since
gone — so a backtest sees the same opportunity set the live trader faced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable


@dataclass(frozen=True)
class UniverseMember:
    """One instrument and the window during which it was tradable.

    ``delisted_at is None`` means still active. For a Polymarket market this is
    the resolution time; for a token, the delisting time.
    """

    instrument_id: str
    listed_at: datetime
    delisted_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.delisted_at is not None and self.delisted_at < self.listed_at:
            raise ValueError(
                f"delisted_at {self.delisted_at} precedes listed_at {self.listed_at} "
                f"for {self.instrument_id}"
            )

    def active_at(self, when: datetime) -> bool:
        if when < self.listed_at:
            return False
        if self.delisted_at is not None and when >= self.delisted_at:
            return False
        return True

    def active_during(self, start: datetime, end: datetime) -> bool:
        """True if the member was tradable at any point in [start, end)."""
        if end <= self.listed_at:
            return False
        if self.delisted_at is not None and start >= self.delisted_at:
            return False
        return True


class PointInTimeUniverse:
    """A collection of members queryable by as-of time, without survivor bias."""

    def __init__(self, members: Iterable[UniverseMember] | None = None) -> None:
        self._members: dict[str, UniverseMember] = {}
        for member in members or []:
            self.add(member)

    def add(self, member: UniverseMember) -> None:
        self._members[member.instrument_id] = member

    def add_market(
        self,
        instrument_id: str,
        listed_at: datetime,
        delisted_at: datetime | None = None,
        **metadata: Any,
    ) -> None:
        self.add(UniverseMember(instrument_id, listed_at, delisted_at, dict(metadata)))

    def get(self, instrument_id: str) -> UniverseMember | None:
        return self._members.get(instrument_id)

    def active_as_of(self, when: datetime) -> list[UniverseMember]:
        """Members tradable exactly at ``when`` (survivor-free snapshot)."""
        return sorted(
            (m for m in self._members.values() if m.active_at(when)),
            key=lambda m: m.instrument_id,
        )

    def active_ids_as_of(self, when: datetime) -> list[str]:
        return [m.instrument_id for m in self.active_as_of(when)]

    def constituents_between(self, start: datetime, end: datetime) -> list[UniverseMember]:
        """All members tradable at any point in [start, end)."""
        return sorted(
            (m for m in self._members.values() if m.active_during(start, end)),
            key=lambda m: m.instrument_id,
        )

    def all_members(self) -> list[UniverseMember]:
        return sorted(self._members.values(), key=lambda m: m.instrument_id)

    def delisted_before(self, when: datetime) -> list[UniverseMember]:
        return sorted(
            (
                m
                for m in self._members.values()
                if m.delisted_at is not None and m.delisted_at <= when
            ),
            key=lambda m: m.instrument_id,
        )

    def survivorship_excluded(self, as_of: datetime, reference: datetime) -> list[str]:
        """Instruments active at ``as_of`` but gone by ``reference``.

        These are exactly the members a survivor-biased universe (built only
        from instruments still alive at ``reference``) would wrongly omit.
        """
        alive_now = set(self.active_ids_as_of(reference))
        return [
            m.instrument_id
            for m in self.active_as_of(as_of)
            if m.instrument_id not in alive_now
        ]

    def __len__(self) -> int:
        return len(self._members)


__all__ = ["PointInTimeUniverse", "UniverseMember"]
