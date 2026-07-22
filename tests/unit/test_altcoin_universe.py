from libs.crypto.discovery.models import AlphaToken, FuturesContract
from libs.crypto.discovery.universe import build_universe, normalize_symbol


def alpha(symbol: str, address: str, chain_id: str = "56") -> AlphaToken:
    return AlphaToken(
        chain_id=chain_id,
        contract_address=address,
        symbol=symbol,
        is_alpha=True,
    )


def future(base_asset: str) -> FuturesContract:
    return FuturesContract(
        symbol=f"{base_asset}USDT",
        base_asset=base_asset,
        quote_asset="USDT",
        status="TRADING",
    )


def test_normalization_preserves_unicode_and_rejects_empty():
    assert normalize_symbol("我踏马来了") == "我踏马来了"
    assert normalize_symbol("Mog") == "MOG"
    assert normalize_symbol("---") is None


def test_exact_symbol_maps_uniquely():
    result = build_universe([alpha("VELVET", "0x1")], [future("VELVET")])

    assert result.candidates[0].futures_symbol == "VELVETUSDT"
    assert result.candidates[0].mapping_status == "unique"


def test_multiplier_contract_maps_uniquely():
    result = build_universe([alpha("Mog", "0x1", "1")], [future("1000000MOG")])

    assert result.candidates[0].futures_symbol == "1000000MOGUSDT"
    assert result.candidates[0].mapping_status == "unique"


def test_duplicate_alpha_symbol_is_not_trade_eligible():
    result = build_universe(
        [alpha("BOB", "0x1"), alpha("BOB", "0x2")],
        [future("1000000BOB")],
    )

    assert {item.mapping_status for item in result.candidates} == {"ambiguous"}
    assert all("AMBIGUOUS_SYMBOL_MAPPING" in item.vetoes for item in result.candidates)


def test_non_ascii_symbols_do_not_collapse_into_one_key():
    result = build_universe(
        [alpha("客服小何", "0x1"), alpha("我踏马来了", "0x2")],
        [future("我踏马来了")],
    )

    by_symbol = {item.symbol: item for item in result.candidates}
    assert by_symbol["客服小何"].mapping_status == "unmatched"
    assert by_symbol["我踏马来了"].mapping_status == "unique"


def test_universe_reports_chain_and_mapping_counts():
    result = build_universe(
        [alpha("VELVET", "0x1"), alpha("MEW", "sol", "CT_501")],
        [future("VELVET"), future("MEW")],
    )

    assert result.counts == {
        "alpha_total": 2,
        "futures_total": 2,
        "unique_intersection": 2,
        "ambiguous": 0,
        "unmatched": 0,
    }
    assert result.chain_counts == {"56": 1, "CT_501": 1}
