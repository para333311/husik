from datetime import date

from husik.blog.monitor import build_keywords, is_within_days


def test_build_keywords_includes_normalized_and_spaced_forms():
    keywords = build_keywords("2024타경12345", "강남 아파트", "서울시 강남구")
    assert "2024타경12345" in keywords
    assert "2024 타경 12345" in keywords
    assert "강남 아파트 2024타경12345" in keywords
    assert "서울시 강남구 2024타경12345" in keywords


def test_build_keywords_dedupes_when_title_equals_case_number():
    keywords = build_keywords("2024타경12345", "2024타경12345", "")
    assert keywords.count("2024타경12345") == 1


def test_is_within_days_true_for_recent_post():
    assert is_within_days("20260801", days=7, today=date(2026, 8, 6))


def test_is_within_days_false_for_old_post():
    assert not is_within_days("20260101", days=7, today=date(2026, 8, 6))


def test_is_within_days_false_for_invalid_date():
    assert not is_within_days("not-a-date", days=7, today=date(2026, 8, 6))
