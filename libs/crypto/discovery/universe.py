"""Build the live Binance Alpha and USD-M perpetual intersection."""

from __future__ import annotations

from dataclasses import dataclass
import unicodedata

from .models import AlphaToken, DiscoveryCandidate, FuturesContract


@dataclass(frozen=True)
class UniverseResult:
    candidates: list[DiscoveryCandidate]
    counts: dict[str, int]
    chain_counts: dict[str, int]


def normalize_symbol(value: str) -> str | None:
    normalized = unicodedata.normalize("NFC", value).strip().casefold().upper()
    normalized = "".join(
        character for character in normalized if character.isalnum() or character == "$"
    )
    return normalized or None


def futures_variants(symbol: str) -> tuple[str, str, str, str]:
    return symbol, f"1000{symbol}", f"1000000{symbol}", f"1M{symbol}"


def build_universe(
    alpha_tokens: list[AlphaToken],
    futures_contracts: list[FuturesContract],
) -> UniverseResult:
    alpha = [token for token in alpha_tokens if token.is_alpha]
    alpha_groups: dict[str, list[AlphaToken]] = {}
    invalid_assets: set[str] = set()
    for token in alpha:
        key = normalize_symbol(token.symbol)
        if key is None:
            invalid_assets.add(token.asset_id)
            continue
        alpha_groups.setdefault(key, []).append(token)

    futures_by_base: dict[str, list[FuturesContract]] = {}
    for contract in futures_contracts:
        if not (
            contract.status == "TRADING"
            and contract.contract_type == "PERPETUAL"
            and contract.quote_asset == "USDT"
        ):
            continue
        key = normalize_symbol(contract.base_asset)
        if key is not None:
            futures_by_base.setdefault(key, []).append(contract)

    candidates: list[DiscoveryCandidate] = []
    for token in alpha:
        key = normalize_symbol(token.symbol)
        vetoes: list[str] = []
        matches: list[FuturesContract] = []
        if token.asset_id in invalid_assets or key is None:
            mapping_status = "unmatched"
            vetoes.append("INVALID_SYMBOL")
        else:
            for variant in futures_variants(key):
                matches.extend(futures_by_base.get(variant, []))
            matches = list({match.symbol: match for match in matches}.values())
            duplicate_alpha = len(alpha_groups.get(key, [])) > 1
            if duplicate_alpha or len(matches) > 1:
                mapping_status = "ambiguous"
                vetoes.append("AMBIGUOUS_SYMBOL_MAPPING")
            elif len(matches) == 1:
                mapping_status = "unique"
            else:
                mapping_status = "unmatched"
                vetoes.append("NO_LIVE_USDT_PERPETUAL")

        if token.blacklisted:
            vetoes.append("BINANCE_TOKEN_BLACKLISTED")

        futures_symbol = matches[0].symbol if len(matches) == 1 else None
        status = "watch" if mapping_status == "unique" and not vetoes else "vetoed"
        candidates.append(
            DiscoveryCandidate(
                asset_id=token.asset_id,
                chain_id=token.chain_id,
                contract_address=token.contract_address,
                symbol=token.symbol,
                futures_symbol=futures_symbol,
                mapping_status=mapping_status,
                price=token.price,
                market_cap=token.market_cap,
                liquidity=token.liquidity,
                volume_24h=token.volume_24h,
                vetoes=vetoes,
                status=status,
            )
        )

    counts = {
        "alpha_total": len(alpha),
        "futures_total": len(futures_contracts),
        "unique_intersection": sum(item.mapping_status == "unique" for item in candidates),
        "ambiguous": sum(item.mapping_status == "ambiguous" for item in candidates),
        "unmatched": sum(item.mapping_status == "unmatched" for item in candidates),
    }
    chain_counts: dict[str, int] = {}
    for item in candidates:
        if item.mapping_status == "unique":
            chain_counts[item.chain_id] = chain_counts.get(item.chain_id, 0) + 1

    return UniverseResult(candidates=candidates, counts=counts, chain_counts=chain_counts)
