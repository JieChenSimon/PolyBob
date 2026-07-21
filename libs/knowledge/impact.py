"""Cross-asset impact analysis for market news headlines.

Given a news headline (plus optional summary / provider category / related
tickers) this module estimates which asset classes the story bears on and in
which direction — the "Bloomberg-style" read of *what this means for stocks,
crypto, gold, FX, rates and oil*.

Two engines, layered:

- :func:`analyze_impact` — a deterministic, explainable heuristic. It runs with
  no external dependency or API key, so the news terminal always has impact
  tags. Each :class:`AssetImpact` carries the terms that triggered it so the UI
  (and a reviewer) can see *why*.
- :class:`ClaudeImpactEnhancer` — an optional best-effort layer that asks Claude
  for a richer read when an ``ANTHROPIC_API_KEY`` is configured. It never raises
  into ingestion; on any failure the heuristic result stands.

Directions are ``bullish`` / ``bearish`` / ``mixed`` / ``neutral`` from the
*asset's* perspective, including a simple safe-haven inversion: risk-off news
that is bearish for equities/crypto is treated as mildly bullish for gold and
the US dollar.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

ASSET_CLASSES: tuple[str, ...] = ("us_equities", "crypto", "gold", "fx", "rates", "oil")

# Asset-class relevance lexicons. Matching is word-boundary, case-insensitive.
_ASSET_KEYWORDS: dict[str, tuple[str, ...]] = {
    "crypto": (
        "bitcoin", "btc", "ethereum", "eth", "crypto", "cryptocurrency", "blockchain",
        "stablecoin", "coinbase", "binance", "altcoin", "defi", "solana", "xrp",
        "spot etf", "digital asset", "on-chain", "onchain",
    ),
    "gold": ("gold", "xau", "bullion", "precious metal", "precious metals", "silver"),
    "us_equities": (
        "s&p", "s&p 500", "nasdaq", "dow jones", "dow ", "stocks", "equities",
        "wall street", "shares", "ipo", "nyse", "earnings", "buyback", "russell",
    ),
    "fx": (
        "dollar", "greenback", "forex", "currency", "euro", "yen", "sterling",
        "dxy", "exchange rate", "yuan", "renminbi",
    ),
    "rates": (
        "fed", "federal reserve", "interest rate", "interest rates", "treasury",
        "treasuries", "yield", "yields", "bond", "bonds", "fomc", "rate cut",
        "rate hike", "inflation", "cpi", "ppi", "monetary policy", "powell",
    ),
    "oil": ("oil", "crude", "opec", "brent", "wti", "petroleum", "energy prices"),
}

# Directional lexicons (general market sentiment).
_BULLISH_TERMS: tuple[str, ...] = (
    "surge", "surges", "rally", "rallies", "soar", "soars", "jump", "jumps",
    "gain", "gains", "rise", "rises", "rebound", "record high", "all-time high",
    "beat", "beats", "upgrade", "upgraded", "boost", "boosts", "optimism",
    "inflow", "inflows", "approval", "approved", "recover", "recovery", "bullish",
    "outperform", "strong demand", "cut rates", "rate cut", "stimulus",
)
_BEARISH_TERMS: tuple[str, ...] = (
    "plunge", "plunges", "drop", "drops", "fall", "falls", "slump", "slumps",
    "crash", "crashes", "selloff", "sell-off", "tumble", "tumbles", "miss",
    "misses", "downgrade", "downgraded", "fear", "fears", "outflow", "outflows",
    "ban", "banned", "hike rates", "rate hike", "sanction", "sanctions",
    "default", "recession", "bearish", "warning", "warns", "lawsuit", "probe",
    "hack", "exploit", "collapse", "layoffs", "weak demand",
)

# Themes that flip direction for specific asset classes regardless of the raw
# sentiment count. Keyed by (theme_terms) -> {asset_class: direction}.
_HAWKISH_TERMS = ("rate hike", "hike rates", "hawkish", "higher for longer", "hot inflation", "cpi rises")
_DOVISH_TERMS = ("rate cut", "cut rates", "dovish", "cooling inflation", "cpi falls", "disinflation")

# Systemic / macro risk terms. Broad risk-off news spills over to safe havens
# (gold, dollar) and equities even when those assets are not named.
_SYSTEMIC_RISK_TERMS = (
    "recession", "geopolitical", "war", "conflict", "crisis", "pandemic",
    "default", "sanction", "sanctions", "shutdown", "contagion", "systemic",
)

# Related-ticker → asset class hints (Finnhub `related` field).
_TICKER_ASSET_HINTS: dict[str, str] = {
    "BTC": "crypto", "ETH": "crypto", "SOL": "crypto", "XRP": "crypto",
    "GLD": "gold", "XAU": "gold", "GC": "gold",
    "DXY": "fx", "EUR": "fx", "JPY": "fx",
    "USO": "oil", "CL": "oil", "BNO": "oil",
    "TLT": "rates", "SPY": "us_equities", "QQQ": "us_equities", "DIA": "us_equities",
}


@dataclass(frozen=True)
class AssetImpact:
    asset_class: str
    direction: str  # bullish | bearish | mixed | neutral
    confidence: float  # 0..1
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ImpactAnalysis:
    sentiment: str  # overall: bullish | bearish | mixed | neutral
    impacts: list[AssetImpact] = field(default_factory=list)
    engine: str = "heuristic"

    def to_metadata(self) -> dict[str, Any]:
        return {
            "sentiment": self.sentiment,
            "analysis_engine": self.engine,
            "impacts": [impact.to_dict() for impact in self.impacts],
        }

    @property
    def asset_tags(self) -> list[str]:
        return [impact.asset_class for impact in self.impacts]


def _matches(text: str, terms: Iterable[str]) -> list[str]:
    found: list[str] = []
    for term in terms:
        # Word-boundary match; terms may contain spaces / punctuation.
        pattern = r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?![a-z0-9])"
        if re.search(pattern, text):
            found.append(term)
    return found


def _round(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 2)


def analyze_impact(
    headline: str,
    *,
    summary: str = "",
    category: str | None = None,
    related: Iterable[str] | None = None,
) -> ImpactAnalysis:
    """Heuristic cross-asset impact read for one news item.

    Deterministic and dependency-free: matches asset-class and directional
    lexicons over the headline+summary, applies a dollar/gold safe-haven
    inversion under risk-off news, and returns per-asset directional impacts
    each annotated with the matched terms.
    """
    text = f"{headline} {summary}".lower()

    # 1) Which asset classes are in scope?
    relevant: dict[str, list[str]] = {}
    for asset_class, keywords in _ASSET_KEYWORDS.items():
        hits = _matches(text, keywords)
        if hits:
            relevant[asset_class] = hits

    category_norm = (category or "").strip().lower()
    if category_norm == "crypto":
        relevant.setdefault("crypto", []).append("category:crypto")
    elif category_norm == "forex":
        relevant.setdefault("fx", []).append("category:forex")

    for ticker in related or []:
        hint = _TICKER_ASSET_HINTS.get(str(ticker).upper())
        if hint:
            relevant.setdefault(hint, []).append(f"ticker:{ticker}")

    # 2) Overall directional sentiment from the news text.
    bull = _matches(text, _BULLISH_TERMS)
    bear = _matches(text, _BEARISH_TERMS)
    bull_n, bear_n = len(bull), len(bear)
    if bull_n == 0 and bear_n == 0:
        base = "neutral"
    elif bull_n > bear_n:
        base = "bullish"
    elif bear_n > bull_n:
        base = "bearish"
    else:
        base = "mixed"

    hawkish = bool(_matches(text, _HAWKISH_TERMS))
    dovish = bool(_matches(text, _DOVISH_TERMS))

    # 2b) Cross-asset spillover: some themes move assets that are not named.
    #  - Monetary policy transmits to equities, crypto, gold, FX and rates.
    #  - Systemic risk-off headlines bid up safe havens (gold, dollar) and hit
    #    equities.
    if hawkish or dovish:
        for asset_class in ("us_equities", "crypto", "gold", "fx", "rates"):
            relevant.setdefault(asset_class, []).append("macro:monetary_policy")
    if base == "bearish" and _matches(text, _SYSTEMIC_RISK_TERMS):
        for asset_class in ("us_equities", "gold", "fx"):
            relevant.setdefault(asset_class, []).append("macro:risk_off")

    # 3) Per-asset directional read.
    impacts: list[AssetImpact] = []
    for asset_class, reasons in relevant.items():
        direction = base
        note = ""

        # Monetary-policy cross effects: hawkish is risk-negative but
        # dollar-positive; dovish is the mirror.
        if hawkish and not dovish:
            if asset_class in {"us_equities", "crypto", "gold"}:
                direction = "bearish"
                note = "hawkish policy pressures risk assets"
            elif asset_class == "fx":
                direction = "bullish"
                note = "hawkish policy supports the dollar"
            elif asset_class == "rates":
                direction = "bearish"
                note = "higher rates pressure bond prices"
        elif dovish and not hawkish:
            if asset_class in {"us_equities", "crypto", "gold"}:
                direction = "bullish"
                note = "dovish policy supports risk assets"
            elif asset_class == "fx":
                direction = "bearish"
                note = "dovish policy weakens the dollar"
            elif asset_class == "rates":
                direction = "bullish"
                note = "lower rates lift bond prices"
        elif base == "bearish" and asset_class in {"gold", "fx"}:
            # Safe-haven inversion under risk-off headlines.
            direction = "bullish"
            note = "risk-off / safe-haven demand"
        elif base == "bullish" and asset_class in {"gold", "fx"}:
            direction = "mixed"
            note = "risk-on trims safe-haven demand"

        signal_count = len(reasons) + (bull_n if direction == "bullish" else bear_n if direction == "bearish" else 0)
        confidence = _round(0.35 + 0.12 * signal_count)

        matched_terms = ", ".join(dict.fromkeys(reasons + bull + bear))[:180]
        rationale = note or f"matched: {matched_terms}" if matched_terms else "keyword relevance"
        if note and matched_terms:
            rationale = f"{note} ({matched_terms})"

        impacts.append(
            AssetImpact(
                asset_class=asset_class,
                direction=direction,
                confidence=confidence,
                rationale=rationale,
            )
        )

    # Stable, most-confident-first ordering.
    impacts.sort(key=lambda impact: impact.confidence, reverse=True)
    return ImpactAnalysis(sentiment=base, impacts=impacts, engine="heuristic")


class ClaudeImpactEnhancer:
    """Optional Claude-backed enrichment of the heuristic impact read.

    Best-effort: any failure (no client, API error, malformed response) leaves
    the heuristic analysis untouched, so news ingestion never depends on it.
    """

    def __init__(self, llm_client: Any | None, *, model: str = "claude-sonnet-5") -> None:
        self.llm_client = llm_client
        self.model = model

    @property
    def available(self) -> bool:
        return self.llm_client is not None

    async def enhance(self, headline: str, summary: str, base: ImpactAnalysis) -> ImpactAnalysis:
        if not self.available:
            return base
        try:
            prompt = (
                "You are a markets desk analyst. For the news below, return JSON "
                '{"sentiment":"bullish|bearish|mixed|neutral","impacts":[{"asset_class":'
                '"us_equities|crypto|gold|fx|rates|oil","direction":"bullish|bearish|mixed|neutral",'
                '"confidence":0-1,"rationale":"short"}]}. Only include asset classes that are '
                f"genuinely affected.\n\nHeadline: {headline}\nSummary: {summary}"
            )
            response = await self.llm_client.messages.create(
                model=self.model,
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
            text = _extract_claude_text(response)
            parsed = _parse_impact_json(text)
            if parsed is None:
                return base
            return parsed
        except Exception:
            return base


def _extract_claude_text(response: Any) -> str:
    content = getattr(response, "content", None)
    if isinstance(content, list) and content:
        block = content[0]
        return getattr(block, "text", "") or (block.get("text", "") if isinstance(block, dict) else "")
    return str(content or "")


def _parse_impact_json(text: str) -> ImpactAnalysis | None:
    import json

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    raw_impacts = data.get("impacts")
    if not isinstance(raw_impacts, list):
        return None
    impacts: list[AssetImpact] = []
    for item in raw_impacts:
        if not isinstance(item, dict):
            continue
        asset_class = str(item.get("asset_class", "")).strip()
        if asset_class not in ASSET_CLASSES:
            continue
        try:
            confidence = _round(float(item.get("confidence", 0.5)))
        except (TypeError, ValueError):
            confidence = 0.5
        impacts.append(
            AssetImpact(
                asset_class=asset_class,
                direction=str(item.get("direction", "neutral")).strip() or "neutral",
                confidence=confidence,
                rationale=str(item.get("rationale", ""))[:200],
            )
        )
    if not impacts:
        return None
    sentiment = str(data.get("sentiment", "neutral")).strip() or "neutral"
    return ImpactAnalysis(sentiment=sentiment, impacts=impacts, engine="heuristic+claude")


__all__ = [
    "ASSET_CLASSES",
    "AssetImpact",
    "ImpactAnalysis",
    "ClaudeImpactEnhancer",
    "analyze_impact",
]
