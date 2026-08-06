from husik.utils.text import (
    dollar_count,
    extract_case_numbers,
    extract_dollar_rating,
    extract_title_candidates,
    normalize_case_number,
)


def test_normalize_case_number_no_space():
    assert normalize_case_number("2024타경12345") == "2024타경12345"


def test_normalize_case_number_with_spaces():
    assert normalize_case_number("2024 타경 12345") == "2024타경12345"


def test_extract_case_numbers_dedup_preserves_order():
    text = "사건번호 2024타경12345 참고\n다시 2024 타경 12345\n2025타경1"
    assert extract_case_numbers(text) == ["2024타경12345", "2025타경1"]


def test_extract_case_numbers_empty():
    assert extract_case_numbers("아무 내용 없음") == []


def test_extract_dollar_rating_picks_longest():
    assert extract_dollar_rating("등급: $$ 그리고 $$$$") == "$$$$"


def test_extract_dollar_rating_none():
    assert extract_dollar_rating("등급 없음") is None


def test_dollar_count():
    assert dollar_count("$$$$") == 4
    assert dollar_count(None) == 0


def test_extract_title_candidates_skips_case_and_dollar_lines():
    text = "강남 아파트 특급매물\n2024타경12345\n$$$$\n"
    candidates = extract_title_candidates(text)
    assert candidates == ["강남 아파트 특급매물"]
