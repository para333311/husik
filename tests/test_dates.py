from datetime import date

from husik.utils.dates import format_deadline_label, parse_date


def test_parse_date_dash_format():
    assert parse_date("매각기일 2026-08-20") == date(2026, 8, 20)


def test_parse_date_korean_format():
    assert parse_date("매각기일 2026년 8월 20일") == date(2026, 8, 20)


def test_parse_date_none_when_missing():
    assert parse_date("날짜 없음") is None


def test_format_deadline_label_unknown():
    assert format_deadline_label(None) == "입찰일 확인중"


def test_format_deadline_label_future():
    label = format_deadline_label(date(2026, 8, 20), today=date(2026, 8, 6))
    assert label == "2026-08-20 입찰 D-14"


def test_format_deadline_label_past():
    label = format_deadline_label(date(2026, 8, 1), today=date(2026, 8, 6))
    assert label == "2026-08-01 입찰 D+5"
