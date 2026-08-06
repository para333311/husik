from husik.utils.text import (
    RATING_3,
    RATING_4,
    RATING_5,
    RATING_LOW,
    RATING_UNKNOWN,
    classify_rating,
    dollar_count,
    extract_case_numbers,
    extract_dollar_rating,
    extract_title_candidates,
    looks_like_uncertain_case_marker,
    normalize_case_number,
    rating_to_count,
)


def test_normalize_case_number_no_space():
    assert normalize_case_number("2024타경12345") == "2024타경12345"


def test_normalize_case_number_with_spaces():
    assert normalize_case_number("2024 타경 12345") == "2024타경12345"


def test_normalize_case_number_space_before_only():
    assert normalize_case_number("2025 타경102095") == "2025타경102095"


def test_normalize_case_number_space_after_only():
    assert normalize_case_number("2025타경 102095") == "2025타경102095"


def test_normalize_case_number_allows_seven_digit_numbers():
    assert normalize_case_number("2025타경1234567") == "2025타경1234567"


def test_extract_case_numbers_finds_all_spacing_variants():
    text = "2025타경102095 / 2025 타경 102095 / 2025타경 102095 / 2025 타경102095 / 2024타경12345"
    assert extract_case_numbers(text) == ["2025타경102095", "2024타경12345"]


def test_extract_case_numbers_dedup_preserves_order():
    text = "사건번호 2024타경12345 참고\n다시 2024 타경 12345\n2025타경1234"
    assert extract_case_numbers(text) == ["2024타경12345", "2025타경1234"]


def test_extract_case_numbers_rejects_short_serial():
    # 사건번호 일련번호는 4~8자리만 인정한다.
    assert extract_case_numbers("2025타경1") == []
    assert extract_case_numbers("2025타경12") == []
    assert extract_case_numbers("2025타경123") == []


def test_looks_like_uncertain_case_marker_true_when_digits_missing():
    assert looks_like_uncertain_case_marker("2025타경") is True
    assert looks_like_uncertain_case_marker("2025 타 경") is True


def test_looks_like_uncertain_case_marker_false_when_no_marker_at_all():
    assert looks_like_uncertain_case_marker("소재지: 서울시 강남구") is False


def test_looks_like_uncertain_case_marker_false_when_full_case_number_present():
    assert looks_like_uncertain_case_marker("2025타경102095") is False


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


# --- classify_rating: 필터가 아니라 분류 태그 -----------------------------------


def test_classify_rating_case_number_only_no_rating_hint():
    text = "2025타경102095"
    assert classify_rating(text) == RATING_UNKNOWN


def test_classify_rating_dollar_signs():
    text = "2025타경102095\n사당 15 추천 $$$"
    assert classify_rating(text) == RATING_3


def test_classify_rating_s_letters_near_keyword():
    text = "2025타경102095\n사당 15 추천 SSS"
    assert classify_rating(text) == RATING_3


def test_classify_rating_digit_near_keyword():
    text = "2025타경102095\n사당 15 추천 3"
    assert classify_rating(text) == RATING_3


def test_classify_rating_two_dollar_signs_is_low_grade():
    text = "2025타경102095\n추천 $$"
    assert classify_rating(text) == RATING_LOW


def test_classify_rating_digit_word_form():
    assert classify_rating("추천 매물, 4달러 등급") == RATING_4


def test_classify_rating_five_dollar_signs():
    assert classify_rating("추천 $$$$$") == RATING_5


def test_classify_rating_bare_digit_without_keyword_is_ignored():
    # "추천"/"등급"/"달러" 근처가 아니면 숫자 3/4/5를 등급으로 보지 않는다.
    text = "물건번호 3, 낙찰가 4억 5천만원"
    assert classify_rating(text) == RATING_UNKNOWN


def test_classify_rating_bare_s_letters_without_keyword_is_ignored():
    text = "SSS 브랜드 매장 임대"
    assert classify_rating(text) == RATING_UNKNOWN


def test_rating_to_count_mapping():
    assert rating_to_count(RATING_5) == 5
    assert rating_to_count(RATING_4) == 4
    assert rating_to_count(RATING_3) == 3
    assert rating_to_count(RATING_LOW) == 0
    assert rating_to_count(RATING_UNKNOWN) == 0
    assert rating_to_count(None) == 0
