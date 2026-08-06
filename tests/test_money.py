from husik.utils.money import format_money, format_rate, parse_money


def test_parse_money_with_commas():
    assert parse_money("감정가 500,000,000원") == 500_000_000


def test_parse_money_none_when_missing():
    assert parse_money("금액 없음") is None


def test_format_money_known():
    assert format_money(500_000_000) == "500,000,000원"


def test_format_money_unknown():
    assert format_money(None) == "확인중"


def test_format_rate():
    assert format_rate(87.5) == "87.5%"
    assert format_rate(None) == "확인중"
