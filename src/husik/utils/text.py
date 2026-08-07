"""사건번호, 달러등급, 제목 후보를 텍스트에서 추출하는 유틸리티."""
from __future__ import annotations

import re
from datetime import date

# 20xx + 타경 + 숫자 4~8자리. 공백은 연도/타/경/일련번호 사이 어디에 있어도 허용한다.
CASE_NUMBER_PATTERN = re.compile(r"(20\d{2})\s*타\s*경\s*(\d{4,8})")
DOLLAR_PATTERN = re.compile(r"\${1,10}")

# "2025타경" 비슷한 글자는 있는데 뒤에 4자리 이상 숫자가 확실히 붙지 않는 경우
# (OCR 깨짐 등으로 사건번호를 온전히 못 뽑은 경우) — 이 페이지를 직전 사건에
# 무작정 이어붙이지 않고 "검토필요"로 분리하기 위한 신호로 쓴다.
UNCERTAIN_CASE_MARKER_RE = re.compile(r"20\d{2}\s*타\s*경(?!\s*\d{4,8})")

# --- 달러등급 분류 (필터가 아니라 분류 태그로만 사용) ---------------------------------
# 순수 $/＄ 기호는 개수 그대로 인정한다 (기존 동작 유지, "추천 $$$" 형태도 매칭됨).
DOLLAR_CHAR_CLASS_RE = re.compile(r"[$＄]")
DOLLAR_RUN_RE = re.compile(r"(?:[$＄]\s*){1,10}")
# S/s 반복(SSS, SSSS...)은 "추천"/"등급"/"달러" 근처에 있을 때만 등급 후보로 인정한다.
S_LETTER_RUN_RE = re.compile(r"[Ss]{3,10}")
# "추천 3", "등급4" 처럼 키워드 바로 뒤(4자 이내)에 오는 3/4/5 숫자만 등급 후보로 인정한다.
RATING_KEYWORD_DIGIT_RE = re.compile(r"(?:추천|등급)\D{0,4}([345])(?!\d)")
# "3달러", "4 달러" 처럼 숫자+"달러" 조합은 그 자체로 등급 후보다.
DIGIT_DOLLAR_WORD_RE = re.compile(r"([345])\s*달러")

RATING_5 = "$$$$$"
RATING_4 = "$$$$"
RATING_3 = "$$$"
RATING_LOW = "낮은등급"
RATING_UNKNOWN = "등급확인"

SALE_DATE_LABEL_RE = re.compile(r"매각\s*(?:기\s*일|일)\s*[:：]?\s*", re.IGNORECASE)
SALE_DATE_RE = re.compile(r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})")
STATUS_LINE_RE = re.compile(r"(?:진행\s*상태|상태)\s*[:：]?\s*(낙찰|유찰|변경|취하|기각|진행중|매각)")
STATUS_TOKEN_RE = re.compile(r"\b(낙찰|유찰|변경|취하|기각|진행중|매각)\b")
TITLE_GRADE_RE = re.compile(r"(?:\${2,10}\+?|[Ss]{3,10}|\$\$\+)")
TITLE_BLOCKED_TAG_RE = re.compile(
    r"\[(?:투기과열지구(?:\s*/\s*조정대상지역)?|조정대상지역|토지거래허가구역(?:\s*/\s*조정대상지역)?)\]"
)

_RATING_COUNTS = {RATING_5: 5, RATING_4: 4, RATING_3: 3, RATING_LOW: 0, RATING_UNKNOWN: 0}


def normalize_case_number(raw: str) -> str:
    """"2024 타경 12345" 같은 표기를 "2024타경12345"로 정규화한다."""
    match = CASE_NUMBER_PATTERN.search(raw)
    if not match:
        return raw.strip()
    year, number = match.groups()
    return f"{year}타경{number}"


def extract_case_numbers(text: str) -> list[str]:
    """텍스트에서 등장하는 순서대로 정규화된 사건번호를 중복 없이 추출한다."""
    seen: list[str] = []
    for match in CASE_NUMBER_PATTERN.finditer(text or ""):
        year, number = match.groups()
        normalized = f"{year}타경{number}"
        if normalized not in seen:
            seen.append(normalized)
    return seen


def looks_like_uncertain_case_marker(text: str) -> bool:
    """확실한 사건번호는 못 뽑았지만 "20xx타경" 비슷한 조각이 있는지 확인한다.

    사건번호가 전혀 없는 페이지를 직전 사건에 이어붙일지, "검토필요"로 분리할지
    판단하는 신호로 쓴다 (호출자는 extract_case_numbers가 빈 리스트일 때만 호출할 것).
    """
    return bool(UNCERTAIN_CASE_MARKER_RE.search(text or ""))


def extract_dollar_rating(text: str) -> str | None:
    """텍스트에서 발견된 달러 표시 중 가장 긴(등급이 높은) 것을 반환한다."""
    matches = DOLLAR_PATTERN.findall(text or "")
    if not matches:
        return None
    return max(matches, key=len)


def dollar_count(rating: str | None) -> int:
    return len(rating) if rating else 0


def find_rating_count_candidates(text: str) -> list[int]:
    """등급으로 볼 수 있는 모든 개수 후보를 모은다 (우선순위는 호출자가 max로 결정)."""
    text = text or ""
    candidates: list[int] = []

    for match in DOLLAR_RUN_RE.finditer(text):
        count = len(DOLLAR_CHAR_CLASS_RE.findall(match.group(0)))
        if count:
            candidates.append(count)

    for match in S_LETTER_RUN_RE.finditer(text):
        start, end = match.span()
        context = text[max(0, start - 6) : min(len(text), end + 6)]
        if "추천" in context or "등급" in context or "달러" in context:
            candidates.append(len(match.group(0)))

    for match in RATING_KEYWORD_DIGIT_RE.finditer(text):
        candidates.append(int(match.group(1)))

    for match in DIGIT_DOLLAR_WORD_RE.finditer(text):
        candidates.append(int(match.group(1)))

    return candidates


def classify_rating(text: str) -> str:
    """텍스트에서 달러등급을 분류한다. 필터가 아니라 분류 태그로만 쓰인다.

    5개 이상 -> "$$$$$", 4개 -> "$$$$", 3개 -> "$$$", 1~2개 -> "낮은등급",
    후보를 전혀 못 찾으면 -> "등급확인".
    """
    candidates = find_rating_count_candidates(text)
    if not candidates:
        return RATING_UNKNOWN
    best = max(candidates)
    if best >= 5:
        return RATING_5
    if best == 4:
        return RATING_4
    if best == 3:
        return RATING_3
    if best >= 1:
        return RATING_LOW
    return RATING_UNKNOWN


def rating_to_count(rating: str | None) -> int:
    """Notion "달러개수" 필드용: $$$$$→5, $$$$→4, $$$→3, 낮은등급/등급확인→0."""
    return _RATING_COUNTS.get(rating or "", 0)


def _clean_title_line(line: str) -> str:
    cleaned = TITLE_BLOCKED_TAG_RE.sub("", line)
    return re.sub(r"\s+", " ", cleaned).strip()


def has_title_grade_marker(text: str) -> bool:
    return bool(TITLE_GRADE_RE.search(text or ""))


def extract_title_candidates(text: str, max_candidates: int = 5) -> list[str]:
    """사건번호/달러표시만 있는 줄을 제외한 제목 후보 줄들을 추출한다."""
    candidates: list[str] = []
    for line in (text or "").splitlines():
        stripped = _clean_title_line(line.strip())
        if not stripped or len(stripped) < 2:
            continue
        if "매수맛집" in stripped:
            continue
        compact = stripped.replace(" ", "")
        if DOLLAR_PATTERN.fullmatch(compact):
            continue
        if CASE_NUMBER_PATTERN.fullmatch(stripped) or CASE_NUMBER_PATTERN.fullmatch(compact):
            continue
        if SALE_DATE_LABEL_RE.search(stripped):
            continue
        candidates.append(stripped)
        if len(candidates) >= max_candidates:
            break
    return candidates


def normalize_sale_date(value: date | tuple[int, int, int] | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        year, month, day = value.year, value.month, value.day
    else:
        year, month, day = value
    try:
        d = date(int(year), int(month), int(day))
    except (TypeError, ValueError):
        return None
    return f"{d.year}.{d.month}.{d.day}"


def extract_sale_date(text: str) -> str | None:
    """"매각기일" 주변 날짜를 추출해 `YYYY.M.D` 형식으로 정규화한다."""
    value = text or ""
    for match in SALE_DATE_LABEL_RE.finditer(value):
        window = value[match.start() : match.end() + 80]
        date_match = SALE_DATE_RE.search(window)
        if date_match:
            return normalize_sale_date(tuple(int(x) for x in date_match.groups()))

    for line in value.splitlines():
        if SALE_DATE_LABEL_RE.search(line):
            date_match = SALE_DATE_RE.search(line)
            if date_match:
                return normalize_sale_date(tuple(int(x) for x in date_match.groups()))

    return None


def extract_progress_status(text: str) -> str | None:
    value = text or ""

    line_match = STATUS_LINE_RE.search(value)
    if line_match:
        return line_match.group(1)

    for line in value.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if len(stripped) > 15:
            continue
        token = STATUS_TOKEN_RE.fullmatch(stripped)
        if token:
            return token.group(1)
    return None
