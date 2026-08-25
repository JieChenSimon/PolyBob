"""Small, append-only SEC XBRL fundamentals mirror for quality-gated research.

The SEC companyfacts endpoint is real source data, but it does not expose an
intraday accepted timestamp for every fact.  Rows are therefore stored with the
filing date as the conservative daily availability date and the contract remains
``strict_historical_pit=false`` until a filing/submission timestamp join is added.
Missing tags are left null; they are never inferred from a related concept.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from libs.data import store
from libs.data.data_lake import record_raw
from libs.data.http_client import HttpFetchError, http_get_bytes


CACHE_DIR = Path("data/market_cache/sec_fundamentals")
USER_AGENT = "PolyBob research research@example.com"
TICKER_MAPPING_URL = "https://www.sec.gov/files/company_tickers.json"
TICKER_MAPPING_CACHE = CACHE_DIR / "company_tickers.json"
CIK_BY_SYMBOL = {
    "ADBE": "0000796343",
    "AMD": "0000002488",
    "DIS": "0001744489",
    "F": "0000037996",
    "INTC": "0000050863",
    "MRVL": "0001835632",
    "SNDK": "0002023554",
    "MU": "0000723125",
    "NVDA": "0001045810",
    "TSLA": "0001318605",
    "UPS": "0001090727",
    "WDC": "0000106040",
}

FLOW_TAGS = {
    "revenue": ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"),
    "gross_profit": ("GrossProfit",),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss",),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment",),
}
BALANCE_TAGS = {
    "cash": ("CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
    "total_debt": ("LongTermDebtCurrent", "LongTermDebtNoncurrent"),
    "shares_outstanding": ("EntityCommonStockSharesOutstanding",),
}


class SecFundamentalsUnavailable(RuntimeError):
    pass


def _dynamic_cik_by_symbol() -> dict[str, str]:
    """Load SEC's official ticker/CIK directory with an append-only cache."""
    if TICKER_MAPPING_CACHE.exists():
        raw = TICKER_MAPPING_CACHE.read_bytes()
    else:
        try:
            raw = http_get_bytes(TICKER_MAPPING_URL, timeout=60.0,
                                 headers={"User-Agent": USER_AGENT})
        except HttpFetchError as exc:
            raise SecFundamentalsUnavailable(str(exc)) from exc
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        pending = TICKER_MAPPING_CACHE.with_suffix(".pending")
        pending.write_bytes(raw)
        pending.replace(TICKER_MAPPING_CACHE)
    record_raw("sec_ticker_mapping_raw", raw, source="www.sec.gov", request=TICKER_MAPPING_URL)
    try:
        payload = json.loads(raw)
        return {
            str(item["ticker"]).upper(): f"{int(item['cik_str']):010d}"
            for item in payload.values()
            if item.get("ticker") and item.get("cik_str") is not None
        }
    except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SecFundamentalsUnavailable("invalid SEC ticker mapping payload") from exc


def ticker_directory() -> dict[str, str]:
    """Return the official SEC ticker -> CIK directory for universe discovery."""
    return _dynamic_cik_by_symbol()


def cik_for_symbol(symbol: str) -> str:
    clean = symbol.upper().strip()
    if clean in CIK_BY_SYMBOL:
        return CIK_BY_SYMBOL[clean]
    dynamic = _dynamic_cik_by_symbol().get(clean)
    if dynamic is None:
        raise SecFundamentalsUnavailable(f"no SEC CIK mapping for {symbol}")
    return dynamic


def _payload(symbol: str) -> tuple[dict[str, Any], str, str]:
    cik = cik_for_symbol(symbol)
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    cache = CACHE_DIR / f"CIK{cik}.json"
    if cache.exists():
        raw = cache.read_bytes()
    else:
        try:
            raw = http_get_bytes(url, timeout=60.0, headers={"User-Agent": USER_AGENT})
        except HttpFetchError as exc:
            raise SecFundamentalsUnavailable(str(exc)) from exc
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        pending = cache.with_suffix(".pending")
        pending.write_bytes(raw)
        pending.replace(cache)
    digest = hashlib.sha256(raw).hexdigest()
    record_raw("sec_companyfacts_raw", raw, source="data.sec.gov", request=url)
    return json.loads(raw), digest, url


def _submission_acceptance(symbol: str) -> dict[str, str]:
    """Return SEC accession -> accepted timestamp for the filing index.

    Companyfacts exposes ``filed`` but not the timestamp at which a filing was
    accepted.  The submissions endpoint is a separate, cacheable source.  A
    missing accession remains missing; it is never replaced with an inferred
    midnight timestamp.
    """
    cik = cik_for_symbol(symbol)
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    cache = CACHE_DIR / f"CIK{cik}.submissions.json"
    if cache.exists():
        raw = cache.read_bytes()
    else:
        try:
            raw = http_get_bytes(url, timeout=60.0, headers={"User-Agent": USER_AGENT})
        except HttpFetchError as exc:
            raise SecFundamentalsUnavailable(str(exc)) from exc
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        pending = cache.with_suffix(".pending")
        pending.write_bytes(raw)
        pending.replace(cache)
    record_raw("sec_submissions_raw", raw, source="data.sec.gov", request=url)
    document = json.loads(raw)
    sources = [document.get("filings", {}).get("recent", {})]
    # SEC moves older submissions into separately named JSON files.  Company
    # facts often reaches much further back than the recent index, so omitting
    # these files would systematically turn older otherwise auditable filings
    # into UNKNOWN.  Each file is cached independently and fetched serially.
    for item in document.get("filings", {}).get("files", []):
        name = str(item.get("name", ""))
        if not name.endswith(".json"):
            continue
        historical_url = f"https://data.sec.gov/submissions/{name}"
        historical_cache = CACHE_DIR / name
        try:
            if historical_cache.exists():
                historical_raw = historical_cache.read_bytes()
            else:
                historical_raw = http_get_bytes(
                    historical_url, timeout=60.0, headers={"User-Agent": USER_AGENT}
                )
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                pending = historical_cache.with_suffix(".pending")
                pending.write_bytes(historical_raw)
                pending.replace(historical_cache)
            record_raw("sec_submissions_raw", historical_raw,
                       source="data.sec.gov", request=historical_url)
            sources.append(json.loads(historical_raw))
        except (HttpFetchError, json.JSONDecodeError):
            # Partial historical coverage is explicitly reflected by missing
            # accession timestamps; never synthesize a timestamp on failure.
            continue
    accepted: dict[str, str] = {}
    for source in sources:
        accession = source.get("accessionNumber", [])
        timestamps = source.get("acceptanceDateTime", [])
        accepted.update({
        str(acc): str(stamp)
        for acc, stamp in zip(accession, timestamps)
        if acc and stamp
        })
    return accepted


def _facts(facts: dict[str, Any], names: tuple[str, ...]) -> list[dict[str, Any]]:
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    out: list[dict[str, Any]] = []
    for name in names:
        out.extend(us_gaap.get(name, {}).get("units", {}).get("USD", []))
        out.extend(us_gaap.get(name, {}).get("units", {}).get("shares", []))
        out.extend(us_gaap.get(name, {}).get("units", {}).get("USD/shares", []))
    return out


def _value_for_filing(facts: dict[str, Any], names: tuple[str, ...], accn: str, end: str) -> float | None:
    candidates = [item for item in _facts(facts, names)
                  if item.get("accn") == accn and item.get("end") == end]
    if not candidates:
        return None
    item = sorted(candidates, key=lambda x: (str(x.get("filed", "")), str(x.get("form", ""))))[-1]
    try:
        return float(item["val"])
    except (KeyError, TypeError, ValueError):
        return None


def materialize(symbol: str, *, as_of: datetime | None = None) -> dict[str, Any]:
    """Mirror SEC filing-period facts into the PIT-aware fundamentals dataset."""
    payload, raw_sha, url = _payload(symbol)
    accepted_by_accession = _submission_acceptance(symbol)
    facts = payload.get("facts", {})
    # One canonical row per filing.  Companyfacts includes comparative prior
    # periods in the same filing; keeping all of them would collide with the
    # store's one-row-per-(symbol,event_date) PIT projection and make selection
    # arbitrary when fetched_at ties.
    filings: dict[tuple[str, str], str] = {}
    for name_set in (*FLOW_TAGS.values(), *BALANCE_TAGS.values()):
        for item in _facts(payload, name_set):
            form = str(item.get("form", ""))
            if form not in {"10-Q", "10-K", "20-F", "40-F"}:
                continue
            accn, end, filed = item.get("accn"), item.get("end"), item.get("filed")
            if accn and end and filed:
                key = (str(accn), str(filed))
                filings[key] = max(str(end), filings.get(key, ""))
    records: list[dict[str, Any]] = []
    for (accn, filed), end in sorted(filings.items()):
        accepted_at = accepted_by_accession.get(accn)
        row: dict[str, Any] = {
            "symbol": symbol.upper(),
            store.EVENT_DATE: filed,
            "period_end": end,
            "announcement_at": accepted_at or f"{filed}T00:00:00+00:00",
            "accepted_at": accepted_at,
            "filing_id": accn,
            "source": "sec_companyfacts",
            "quality_flags": {
                "accepted_at": accepted_at or "missing",
                "raw_sha256": raw_sha,
            },
        }
        for key, names in FLOW_TAGS.items():
            row[key] = _value_for_filing(payload, names, accn, end)
        cash = _value_for_filing(payload, BALANCE_TAGS["cash"], accn, end)
        current = _value_for_filing(payload, ("LongTermDebtCurrent",), accn, end)
        noncurrent = _value_for_filing(payload, ("LongTermDebtNoncurrent",), accn, end)
        row["cash"] = cash
        row["total_debt"] = (current or 0.0) + (noncurrent or 0.0) if current is not None or noncurrent is not None else None
        row["shares_outstanding"] = _value_for_filing(payload, BALANCE_TAGS["shares_outstanding"], accn, end)
        if any(row.get(key) is not None for key in ("revenue", "net_income", "operating_cash_flow")):
            records.append(row)
    observed = as_of or datetime.now(UTC)
    written = store.write(store.FUNDAMENTALS, symbol.upper(), records,
                          fetched_at=observed, deduplicate_payload=True)
    accepted_rows = sum(1 for row in records if row["quality_flags"].get("accepted_at") != "missing")
    return {"symbol": symbol.upper(), "rows": len(records), "written": written,
            "accepted_at_rows": accepted_rows,
            "strict_pit_candidate": bool(records) and accepted_rows == len(records),
            "raw_sha256": raw_sha, "source_url": url, "status": "available" if records else "empty"}


__all__ = ["CIK_BY_SYMBOL", "SecFundamentalsUnavailable", "cik_for_symbol", "materialize"]
