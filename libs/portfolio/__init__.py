"""Portfolio state — the half of "return = edge x size" that had no substrate.

``libs/quant/position_sizing.py`` held Kelly with zero callers, and the product
printed a size derived from a hardcoded 100,000. Neither was a maths problem: there
was no account. :mod:`libs.portfolio.account` is that account, and
:mod:`libs.portfolio.sizing` is Kelly finally connected to it — haircut by how
little independent sample the win rate rests on, capped, and budgeted across edges
so a US long and an altcoin short are not mistaken for a hedge.

Nothing here grants permission to trade; :mod:`libs.quant.promotion_registry` does
that, and today it grants none.
"""

from libs.portfolio.account import Account, AccountNotConfigured, Position
from libs.portfolio.sizing import EdgeStatistics, SizeDecision, size_position

__all__ = [
    "Account", "AccountNotConfigured", "EdgeStatistics", "Position",
    "SizeDecision", "size_position",
]
