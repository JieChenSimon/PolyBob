"""What instruments are in scope — declared once.

The same lists were written out by hand in five scripts, and they had drifted:
``focused_scoreboard`` traded ten US names, ``real_scoreboard`` five,
``us_crypto_experiment`` twenty different ones. That matters more than it looks.
The universe is part of a hypothesis: "insider clusters predict returns" is a
different claim over mega-caps than over all SEC filers, and a study whose
universe is a literal in whichever script happened to run cannot be compared with
one whose universe is a different literal in a different script.

It also silently breaks the multiple-testing correction. Trying an edge on ten
names and then on twenty is two trials, but if the universe lives in the script
nobody records that the second run happened.

So the universe is declared here, named, and referenced. Changing one is then a
visible edit to a shared file rather than a number nudged inside a script.
"""

from __future__ import annotations

from dataclasses import dataclass

# --------------------------------------------------------------- US equities

# Liquid mega/large caps. Used where the study needs *price* history for names
# everybody holds — not where it needs the population of insider filers, which is
# thousands of small caps and comes from SEC Form 345 directly.
US_LIQUID = (
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AMD",
    "JPM", "BAC", "WFC", "C", "XOM", "CVX",
    "PFE", "MRK", "KO", "NKE", "DIS", "VZ", "T", "F", "GM", "GE", "BA", "INTC",
)

# High-volatility semiconductor/cycle names used by the separate deep-drawdown
# research universe. They are deliberately not mixed into the core liquid
# benchmark universe, where a missing 50% drawdown is an expected outcome.
US_CYCLICAL_REBOUND = ("SNDK", "MU", "WDC", "MRVL")

# Benchmarks. SPY is the excess-return baseline for every US event study, so it is
# named here rather than typed as a string in each one.
US_BENCHMARK = "SPY"
US_INDEX_PROXIES = ("SPY", "QQQ")

# --------------------------------------------------------------- A-shares

# The dragon-tiger study runs over the whole market from the exchange feed; this
# shorter list is for the price/technical panels, where a page needs bars for a
# name a person actually watches.
A_SHARE_LIQUID = (
    "600519", "000001", "300750", "601318", "000858", "600036", "000651", "002594",
)
A_SHARE_BENCHMARK = "000300"        # CSI 300

# --------------------------------------------------------------- Altcoins

# The eight majors the retail-crowding study measured. Deliberately excludes BTC
# and ETH: the hypothesis is about levered retail crowding in *alts*, and the two
# largest coins have a different holder base and their own dedicated modules.
ALTCOIN_MAJORS = ("SOL", "DOGE", "ADA", "AVAX", "LINK", "LTC", "XRP", "BCH")


def altcoin_pairs(quote: str = "USDT") -> tuple[str, ...]:
    return tuple(f"{c}-{quote}" for c in ALTCOIN_MAJORS)


def altcoin_swaps(quote: str = "USDT") -> tuple[str, ...]:
    """Perp instrument ids — the funding leg the short is actually traded on."""
    return tuple(f"{c}-{quote}-SWAP" for c in ALTCOIN_MAJORS)


# --------------------------------------------------- the three in-scope domains


@dataclass(frozen=True)
class Domain:
    """One of the project's three instrument classes, and nothing else.

    The scope is fixed: BTC-5m, equities (US + A-share), altcoins. A fourth entry
    here is a scope change, which is a decision, not a convenience.
    """

    key: str
    label_zh: str
    benchmark: str | None
    symbols: tuple[str, ...]


DOMAINS: tuple[Domain, ...] = (
    Domain("us_equity", "美股", US_BENCHMARK, US_LIQUID),
    Domain("a_share", "A股", A_SHARE_BENCHMARK, A_SHARE_LIQUID),
    Domain("altcoin", "山寨币", None, altcoin_pairs()),
)

DOMAIN_KEYS = tuple(d.key for d in DOMAINS)


def domain(key: str) -> Domain:
    for d in DOMAINS:
        if d.key == key:
            return d
    raise KeyError(f"unknown domain '{key}'; in scope: {', '.join(DOMAIN_KEYS)}")


__all__ = [
    "ALTCOIN_MAJORS",
    "A_SHARE_BENCHMARK",
    "A_SHARE_LIQUID",
    "DOMAINS",
    "DOMAIN_KEYS",
    "Domain",
    "US_BENCHMARK",
    "US_INDEX_PROXIES",
    "US_LIQUID",
    "US_CYCLICAL_REBOUND",
    "altcoin_pairs",
    "altcoin_swaps",
    "domain",
]
