"""사건번호 기준으로 페이지를 사건 단위로 묶는다.

- 새 사건번호가 나오면 새 사건 시작.
- 사건번호가 없는 페이지는 직전 사건에 포함.
- 같은 사건번호가 여러 페이지에 반복돼도 하나의 사건으로 유지.
- 달러등급은 사건 시작 페이지 주변(RATING_LOOKAHEAD_PAGES)에서만 판단하고,
  이후 반복되는 달러 표시로 등급이 바뀌지 않는다.

정책(2차): 달러등급은 더 이상 필터가 아니라 분류 태그다. 사건번호가 감지되면
등급과 무관하게 무조건 CaseRecord로 등록된다. 등급을 못 찾으면 "등급확인",
$/$$ 수준으로만 잡히면 "낮은등급"으로 분류한다 (utils.text.classify_rating 참고).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from husik.pdf.ocr import extract_page_text
from husik.pdf.render import RenderedPage
from husik.utils.text import (
    RATING_3,
    RATING_4,
    RATING_5,
    RATING_LOW,
    RATING_UNKNOWN,
    classify_rating,
    extract_case_numbers,
    extract_title_candidates,
    rating_to_count,
)

RATING_LOOKAHEAD_PAGES = 3
MIN_TITLE_LENGTH = 4
_RATING_PRIORITY = {RATING_5: 5, RATING_4: 4, RATING_3: 3, RATING_LOW: 1, RATING_UNKNOWN: 0}


@dataclass
class PageAnalysis:
    page_no: int
    case_numbers: list[str]
    rating: str | None
    title_candidates: list[str]
    raw_text: str
    image_path: Path

    def to_dict(self) -> dict:
        return {
            "page_no": self.page_no,
            "case_numbers": self.case_numbers,
            "rating": self.rating,
            "title_candidates": self.title_candidates,
            "raw_text": self.raw_text,
        }


@dataclass
class CaseRecord:
    case_number: str
    rating: str
    title: str
    page_start: int
    page_end: int
    pages: list[PageAnalysis] = field(default_factory=list)

    @property
    def dollar_count(self) -> int:
        return rating_to_count(self.rating)

    @property
    def image_paths(self) -> list[Path]:
        return [p.image_path for p in self.pages]


def analyze_page(rendered: RenderedPage, openai_api_key: str | None = None) -> PageAnalysis:
    text = extract_page_text(rendered.image_path, rendered.native_text, openai_api_key)
    return PageAnalysis(
        page_no=rendered.page_no,
        case_numbers=extract_case_numbers(text),
        rating=classify_rating(text),
        title_candidates=extract_title_candidates(text),
        raw_text=text,
        image_path=rendered.image_path,
    )


def _pick_title(pages: list[PageAnalysis], fallback: str) -> str:
    for page in pages:
        for candidate in page.title_candidates:
            if len(candidate) >= MIN_TITLE_LENGTH:
                return candidate
    return fallback


def _pick_rating_label(pages: list[PageAnalysis]) -> str:
    """사건 시작 페이지 주변(RATING_LOOKAHEAD_PAGES)에서 가장 높은 등급을 고른다.

    후보가 전혀 없으면(모든 페이지가 "등급확인") "등급확인"을 반환한다 — 더 이상
    필터링 대상이 아니라 분류 태그이므로 None을 반환하지 않는다.
    """
    best = RATING_UNKNOWN
    for page in pages[:RATING_LOOKAHEAD_PAGES]:
        if _RATING_PRIORITY.get(page.rating, 0) > _RATING_PRIORITY.get(best, 0):
            best = page.rating
    return best


def group_pages_into_cases(pages: list[PageAnalysis]) -> list[CaseRecord]:
    records: list[CaseRecord] = []
    current: CaseRecord | None = None

    for page in pages:
        found = page.case_numbers[0] if page.case_numbers else None
        if found and (current is None or found != current.case_number):
            current = CaseRecord(
                case_number=found,
                rating=RATING_UNKNOWN,
                title="",
                page_start=page.page_no,
                page_end=page.page_no,
            )
            records.append(current)

        if current is None:
            continue

        current.pages.append(page)
        current.page_end = page.page_no

    for record in records:
        record.rating = _pick_rating_label(record.pages)
        record.title = _pick_title(record.pages, fallback=record.case_number)

    return records
