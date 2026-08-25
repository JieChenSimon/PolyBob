from libs.data.sec_insider import _parse_date


def test_sec_date_parser_normalizes_common_form345_date_without_strptime():
    assert _parse_date("31-MAR-2026") == "2026-03-31"
    assert _parse_date("bad-date") == ""
