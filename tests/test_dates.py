from datetime import date

from husik.utils.dates import (
    format_compact_date,
    format_deadline_label,
    parse_date,
    parse_sale_date_from_text,
)


def test_parse_date_dash_format():
    assert parse_date("매각기일 2026-08-20") == date(2026, 8, 20)


def test_parse_date_korean_format():
    assert parse_date("매각기일 2026년 8월 20일") == date(2026, 8, 20)


def test_parse_date_none_when_missing():
    assert parse_date("날짜 없음") is None


def test_parse_sale_date_from_text_accepts_dot_zero_padded():
    assert str(parse_sale_date_from_text("매각기일 : 2026.05.19")) == "2026-05-19"


def test_parse_sale_date_from_text_accepts_dot_single_digit():
    assert str(parse_sale_date_from_text("매각 기일 2026.5.19")) == "2026-05-19"


def test_parse_sale_date_from_text_accepts_dash():
    assert str(parse_sale_date_from_text("안내 매각기일: 2026-05-19 예정")) == "2026-05-19"


def test_format_compact_date_without_zero_padding():
    assert format_compact_date(parse_sale_date_from_text("매각기일 2026.05.09")) == "2026.5.9"


def test_format_deadline_label_unknown():
    assert format_deadline_label(None) == "입찰일 확인중"


def test_format_deadline_label_future():
    label = format_deadline_label(date(2026, 8, 20), today=date(2026, 8, 6))
    assert label == "2026-08-20 입찰 D-14"


def test_format_deadline_label_past():
    label = format_deadline_label(date(2026, 8, 1), today=date(2026, 8, 6))
    assert label == "2026-08-01 입찰 D+5"
