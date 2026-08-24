"""Discover equity research candidates from real market rosters and local evidence.

Discovery is intentionally separate from promotion.  A symbol can be present in
an official roster and still be UNKNOWN because PolyBob has no usable, point-in-
time price history for it.  This module never turns a missing field into zero and
never claims that a discovered symbol is safe or profitable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Iterable

from libs.data import store
from libs.data.sec_fundamentals import ticker_directory


@dataclass(frozen=True)
class RosterMember:
    symbol: str
    domain: str
    name: str | None
    roster_source: str


def discover_us_roster() -> list[RosterMember]:
    """Return SEC's current issuer ticker directory, not a hand-maintained list."""
    return [
        RosterMember(symbol, "us_equity", None, "sec_company_tickers")
        for symbol in sorted(ticker_directory())
        if symbol.isascii() and symbol.isalnum() and 1 <= len(symbol) <= 6
    ]


def discover_a_share_roster() -> list[RosterMember]:
    """Return the provider's live A-share code/name roster.

    AkShare is an adapter around real provider data.  An unavailable provider is
    surfaced to the caller; falling back to the eight research symbols would
    make an outage look like a successful discovery.
    """
    try:
        import akshare as ak

        frame = ak.stock_info_a_code_name()
    except Exception as exc:  # noqa: BLE001 - provider errors become UNKNOWN
        raise RuntimeError(f"A 股市场名录不可用: {type(exc).__name__}: {exc}") from exc
    if frame is None or "code" not in frame.columns:
        raise RuntimeError("A 股市场名录响应缺少 code 列")
    name_col = "name" if "name" in frame.columns else None
    result: list[RosterMember] = []
    for row in frame.to_dict("records"):
        symbol = str(row.get("code") or "").strip()
        if len(symbol) != 6 or not symbol.isdigit():
            continue
        result.append(RosterMember(
            symbol=symbol,
            domain="a_share",
            name=str(row[name_col]).strip() if name_col and row.get(name_col) else None,
            roster_source="akshare_stock_info_a_code_name",
        ))
    return sorted({item.symbol: item for item in result}.values(), key=lambda x: x.symbol)


def _coverage(member: RosterMember, min_bars: int, min_dollar_volume: float) -> dict[str, Any]:
    frame = store.read(store.DAILY_BARS, member.symbol)
    rows = len(frame)
    reasons: list[str] = []
    if rows < min_bars:
        reasons.append(f"bars<{min_bars}")
    latest = str(frame[store.EVENT_DATE].max())[:10] if rows else None
    basis_column = frame.get("price_basis", [])
    basis_values = basis_column.tolist() if hasattr(basis_column, "tolist") else list(basis_column)
    bases = {
        str(value) for value in basis_values
        if value is not None and str(value) not in {"", "nan", "None"}
    }
    price_basis = next(iter(bases)) if len(bases) == 1 else ("mixed" if bases else "unknown")
    if price_basis in {"unknown", "mixed"}:
        reasons.append("price_basis_unknown_or_mixed")
    avg_dollar_volume = None
    if rows and "volume" in frame.columns:
        dollar_volume = (frame["close"].astype(float) * frame["volume"].astype(float)).dropna()
        if len(dollar_volume):
            avg_dollar_volume = float(dollar_volume.tail(60).median())
    if avg_dollar_volume is None:
        reasons.append("dollar_volume_unknown")
    elif avg_dollar_volume < min_dollar_volume:
        reasons.append(f"median_dollar_volume<{min_dollar_volume:g}")
    status = "READY_FOR_RESEARCH" if not reasons else "UNKNOWN"
    return {
        **asdict(member),
        "status": status,
        "bars": rows,
        "start": str(frame[store.EVENT_DATE].min())[:10] if rows else None,
        "latest": latest,
        "price_basis": price_basis,
        "median_dollar_volume_60": avg_dollar_volume,
        "reasons": reasons,
    }


def discover_equity_candidates(
    *, domains: Iterable[str] = ("us_equity", "a_share"),
    limit: int | None = None,
    min_bars: int = 200,
    min_dollar_volume: float = 5_000_000.0,
) -> dict[str, Any]:
    """Build a deterministic, auditable candidate manifest from real rosters."""
    members: list[RosterMember] = []
    errors: dict[str, str] = {}
    for domain in domains:
        try:
            members.extend(discover_us_roster() if domain == "us_equity" else discover_a_share_roster())
        except Exception as exc:  # noqa: BLE001 - preserve provider UNKNOWN state
            errors[domain] = f"{type(exc).__name__}: {exc}"
    unique_members = {(member.domain, member.symbol): member for member in members}
    # A full SEC directory can contain thousands of issuers.  A bounded scan is
    # deliberately applied before touching Parquet so discovery cannot turn into
    # an accidental high-intensity disk sweep.  The manifest records the bound;
    # callers wanting a complete scan omit --limit and can schedule it explicitly.
    ordered_members = sorted(unique_members.values(), key=lambda x: (x.domain, x.symbol))
    if limit is not None:
        # Apply the bound per domain: asking for US + A-share discovery must not
        # silently consume the whole budget on whichever domain sorts first.
        bounded: list[RosterMember] = []
        for domain in sorted({member.domain for member in ordered_members}):
            bounded.extend(
                member for member in ordered_members if member.domain == domain
            )
            domain_count = sum(1 for member in ordered_members if member.domain == domain)
            if domain_count > limit:
                start = len(bounded) - domain_count
                bounded = bounded[:start + limit]
        ordered_members = bounded
    rows = [_coverage(member, min_bars, min_dollar_volume) for member in ordered_members]
    rows.sort(key=lambda row: (row["status"] != "READY_FOR_RESEARCH", -row["bars"], row["domain"], row["symbol"]))
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "real_data_only": True,
        "selection_is_not_promotion": True,
        "min_bars": min_bars,
        "min_dollar_volume": min_dollar_volume,
        "limit_per_domain": limit,
        "provider_errors": errors,
        "counts": {
            "total": len(rows),
            "ready_for_research": sum(row["status"] == "READY_FOR_RESEARCH" for row in rows),
            "unknown": sum(row["status"] == "UNKNOWN" for row in rows),
        },
        "candidates": rows,
    }


__all__ = [
    "RosterMember",
    "discover_a_share_roster",
    "discover_equity_candidates",
    "discover_us_roster",
]
