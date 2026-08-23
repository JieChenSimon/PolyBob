"""Typed corporate actions and split-aware raw-price returns."""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from libs.data import store


class CorporateActionType(str, Enum):
    SPLIT = "split"
    CASH_DIVIDEND = "cash_dividend"
    SYMBOL_CHANGE = "symbol_change"
    DELISTING = "delisting"


@dataclass(frozen=True)
class CorporateAction:
    instrument: str
    effective_at: dt.date
    action_type: CorporateActionType
    source: str
    ratio: float | None = None
    cash_amount: float | None = None
    currency: str | None = None
    price_basis_before: str = "raw"
    price_basis_after: str = "raw"

    def validate(self) -> None:
        if not self.instrument.strip() or not self.source.strip():
            raise ValueError("corporate action needs instrument and source")
        if self.action_type is CorporateActionType.SPLIT:
            if self.ratio is None or not math.isfinite(self.ratio) or self.ratio <= 0:
                raise ValueError("split ratio must be finite and positive")
        if self.action_type is CorporateActionType.CASH_DIVIDEND:
            if self.cash_amount is None or not math.isfinite(self.cash_amount):
                raise ValueError("cash dividend amount must be finite")

    def to_store_row(self) -> dict[str, object]:
        self.validate()
        return {
            "symbol": self.instrument.upper(),
            store.EVENT_DATE: self.effective_at.isoformat(),
            "action_type": self.action_type.value,
            "ratio": self.ratio,
            "cash_amount": self.cash_amount,
            "currency": self.currency,
            "source": self.source,
            "price_basis_before": self.price_basis_before,
            "price_basis_after": self.price_basis_after,
        }


def split_factor(
    actions: Iterable[CorporateAction], *, after: dt.date, through: dt.date
) -> float:
    """New shares per original share for splits after entry through exit."""
    factor = 1.0
    for action in actions:
        action.validate()
        if (
            action.action_type is CorporateActionType.SPLIT
            and after < action.effective_at <= through
        ):
            factor *= float(action.ratio)
    return factor


def raw_price_return(
    entry_price: float,
    exit_price: float,
    actions: Iterable[CorporateAction],
    *,
    entry_date: dt.date,
    exit_date: dt.date,
) -> float:
    """Holding-period return on raw prices, neutralising intervening splits."""
    if not all(math.isfinite(value) and value > 0 for value in (entry_price, exit_price)):
        raise ValueError("entry and exit prices must be finite and positive")
    factor = split_factor(actions, after=entry_date, through=exit_date)
    return exit_price * factor / entry_price - 1.0


__all__ = [
    "CorporateAction", "CorporateActionType", "raw_price_return", "split_factor",
]
