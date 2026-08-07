"""사건번호 기준으로 페이지를 사건 단위로 묶는다.

- 새 사건번호가 나오면 새 사건 시작.
- 사건번호가 없는 페이지는 직전 사건에 포함 (단, 확실한 continuation 근거가 없으면
  split_uncertain_continuations로 분리한다 — 아래 참고).
- 같은 사건번호가 여러 페이지에 반복돼도 하나의 사건으로 유지.
- 달러등급은 사건 시작 페이지 주변(RATING_LOOKAHEAD_PAGES)에서만 판단하고,
  이후 반복되는 달러 표시로 등급이 바뀌지 않는다.

정책(2차): 달러등급은 더 이상 필터가 아니라 분류 태그다. 사건번호가 감지되면
등급과 무관하게 무조건 CaseRecord로 등록된다. 등급을 못 찾으면 "등급확인",
$/$$ 수준으로만 잡히면 "낮은등급"으로 분류한다 (utils.text.classify_rating 참고).

정책(3차): 이미지는 더 이상 페이지 전체가 아니라 pdf.segment의 사건 단위 crop을
쓴다 (CaseRecord.image_segments). 사건번호가 없는 continuation 페이지 중
"20xx타경" 비슷한 조각만 있고 완전한 사건번호가 아닌 경우(uncertain_marker)는
다른 사건일 가능성이 있으므로 직전 사건에 붙이지 않고 "검토필요"로 분리한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from husik.pdf.ocr import extract_page_text, openai_vision_case_numbers
from husik.pdf.render import RenderedPage
from husik.pdf.segment import REVIEW_LABEL, ImageSegment, segment_page
from husik.utils.dates import parse_sale_date_from_text
from husik.utils.text import (
    RATING_3,
    RATING_4,
    RATING_5,
    RATING_LOW,
    RATING_UNKNOWN,
    classify_rating,
    extract_case_numbers,
    extract_title_candidates,
    looks_like_uncertain_case_marker,
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
    uncertain_marker: bool = False

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
    sale_date: date | None = None
    pages: list[PageAnalysis] = field(default_factory=list)
    image_segments: list[ImageSegment] = field(default_factory=list)

    @property
    def dollar_count(self) -> int:
        return rating_to_count(self.rating)

    @property
    def image_paths(self) -> list[Path]:
        if self.image_segments:
            return [seg.image_path for seg in self.image_segments]
        return [p.image_path for p in self.pages]

    @property
    def mixed_page_used(self) -> bool:
        return any(seg.from_mixed_page for seg in self.image_segments)


def analyze_page(rendered: RenderedPage, openai_api_key: str | None = None) -> PageAnalysis:
    text = extract_page_text(rendered.image_path, rendered.native_text, openai_api_key)
    case_numbers = extract_case_numbers(text)
    if not case_numbers and openai_api_key:
        case_numbers = openai_vision_case_numbers(rendered.image_path, openai_api_key)
    uncertain = looks_like_uncertain_case_marker(text) if not case_numbers else False
    return PageAnalysis(
        page_no=rendered.page_no,
        case_numbers=case_numbers,
        rating=classify_rating(text),
        title_candidates=extract_title_candidates(text),
        raw_text=text,
        image_path=rendered.image_path,
        uncertain_marker=uncertain,
    )


def _pick_title(pages: list[PageAnalysis], fallback: str) -> str:
    for page in pages:
        for candidate in page.title_candidates:
            if len(candidate) >= MIN_TITLE_LENGTH:
                return candidate
    return fallback


def _pick_sale_date(pages: list[PageAnalysis]) -> date | None:
    for page in pages:
        found = parse_sale_date_from_text(page.raw_text)
        if found is not None:
            return found
    return None


def _pick_rating_label(pages: list[PageAnalysis]) -> str:
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
        record.sale_date = _pick_sale_date(record.pages)

    return records


def split_uncertain_continuations(
    records: list[CaseRecord],
) -> tuple[list[CaseRecord], list[PageAnalysis]]:
    review_pages: list[PageAnalysis] = []

    for record in records:
        kept: list[PageAnalysis] = []
        for index, page in enumerate(record.pages):
            is_first_page = index == 0
            if not is_first_page and not page.case_numbers and page.uncertain_marker:
                review_pages.append(page)
                continue
            kept.append(page)

        if len(kept) != len(record.pages):
            record.pages = kept
            if kept:
                record.page_start = kept[0].page_no
                record.page_end = kept[-1].page_no
                record.rating = _pick_rating_label(kept)
                record.title = _pick_title(kept, fallback=record.case_number)
                record.sale_date = _pick_sale_date(kept)

    return records, review_pages


def assign_image_segments(
    records: list[CaseRecord],
    rendered_pages: list[RenderedPage],
    analyses: list[PageAnalysis],
    work_dir: Path,
) -> list[ImageSegment]:
    by_case: dict[str, CaseRecord] = {r.case_number: r for r in records}
    page_owner: dict[int, CaseRecord] = {}
    for record in records:
        for page in record.pages:
            page_owner[page.page_no] = record

    rendered_by_page = {r.page_no: r for r in rendered_pages}
    review_segments: list[ImageSegment] = []

    for analysis in analyses:
        rendered = rendered_by_page.get(analysis.page_no)
        if rendered is None:
            continue

        if not analysis.case_numbers:
            owner = page_owner.get(analysis.page_no)
            if owner is not None:
                owner.image_segments.append(
                    ImageSegment(
                        case_number=owner.case_number,
                        page_no=analysis.page_no,
                        image_path=rendered.image_path,
                    )
                )
            continue

        for seg in segment_page(rendered, analysis.case_numbers, work_dir):
            if seg.is_review or seg.case_number == REVIEW_LABEL:
                review_segments.append(seg)
                continue

            record = by_case.get(seg.case_number)
            if record is None:
                record = CaseRecord(
                    case_number=seg.case_number,
                    rating=RATING_UNKNOWN,
                    title=seg.case_number,
                    page_start=seg.page_no,
                    page_end=seg.page_no,
                    sale_date=None,
                )
                records.append(record)
                by_case[seg.case_number] = record

            record.image_segments.append(seg)
            record.page_start = min(record.page_start, seg.page_no)
            record.page_end = max(record.page_end, seg.page_no)

    return review_segments


@dataclass
class AnalyzedPdf:
    records: list[CaseRecord]
    review_segments: list[ImageSegment] = field(default_factory=list)


def analyze_pdf_pages(
    rendered_pages: list[RenderedPage],
    analyses: list[PageAnalysis],
    work_dir: Path,
) -> AnalyzedPdf:
    records = group_pages_into_cases(analyses)
    records, review_pages = split_uncertain_continuations(records)
    review_segments = assign_image_segments(records, rendered_pages, analyses, work_dir)

    for page in review_pages:
        review_segments.append(
            ImageSegment(
                case_number=REVIEW_LABEL,
                page_no=page.page_no,
                image_path=page.image_path,
                is_review=True,
            )
        )

    return AnalyzedPdf(records=records, review_segments=review_segments)
