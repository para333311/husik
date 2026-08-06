"""사건번호, 달러등급, 제목 후보를 텍스트에서 추출하는 유틸리티."""
from __future__ import annotations

import re

CASE_NUMBER_PATTERN = re.compile(r"(\d{4})\s*타\s*경\s*(\d{1,6})")
DOLLAR_PATTERN = re.compile(r"\${1,10}")


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


def extract_dollar_rating(text: str) -> str | None:
    """텍스트에서 발견된 달러 표시 중 가장 긴(등급이 높은) 것을 반환한다."""
    matches = DOLLAR_PATTERN.findall(text or "")
    if not matches:
        return None
    return max(matches, key=len)


def dollar_count(rating: str | None) -> int:
    return len(rating) if rating else 0


def extract_title_candidates(text: str, max_candidates: int = 5) -> list[str]:
    """사건번호/달러표시만 있는 줄을 제외한 제목 후보 줄들을 추출한다."""
    candidates: list[str] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped or len(stripped) < 2:
            continue
        compact = stripped.replace(" ", "")
        if DOLLAR_PATTERN.fullmatch(compact):
            continue
        if CASE_NUMBER_PATTERN.fullmatch(stripped) or CASE_NUMBER_PATTERN.fullmatch(compact):
            continue
        candidates.append(stripped)
        if len(candidates) >= max_candidates:
            break
    return candidates
