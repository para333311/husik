"""사건표(좌상단 사건번호) 시작점을 기준으로 페이지를 사건 단위로 묶는다.

핵심 규칙:
- 좌상단(기본 x<=45%, y<=25%)에서 감지된 사건번호만 "새 사건 시작"으로 인정한다.
- 사건번호 없는 페이지는 직전 사건의 "연속 페이지"일 때만 붙인다.
- 페이지 전체/표 단위 중심으로 처리해 과도한 세부 crop 생성을 피한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from husik.pdf.ocr import (
    extract_page_text,
    openai_vision_case_metadata,
    openai_vision_case_numbers,
    tesseract_ocr_regions,
)
from husik.pdf.render import RenderedPage
from husik.pdf.segment import (
    REVIEW_LABEL,
    ImageSegment,
    compose_slides_into_bundles,
    detect_page_layout,
    segment_page,
)
from husik.utils.dates import parse_sale_date_from_text
from husik.utils.text import (
    RATING_3,
    RATING_4,
    RATING_5,
    RATING_LOW,
    RATING_UNKNOWN,
    classify_rating,
    extract_case_numbers,
    extract_progress_status,
    extract_title_candidates,
    has_title_grade_marker,
    looks_like_uncertain_case_marker,
    normalize_sale_date,
    rating_to_count,
)

TOP_LEFT_X_RATIO = 0.45
TOP_LEFT_Y_RATIO = 0.25
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
    page_case_numbers: list[str] = field(default_factory=list)
    status: str | None = None
    sale_date_hint: date | None = None

    def to_dict(self) -> dict:
        return {
            "page_no": self.page_no,
            "case_numbers": self.case_numbers,
            "page_case_numbers": self.page_case_numbers,
            "rating": self.rating,
            "title_candidates": self.title_candidates,
            "raw_text": self.raw_text,
            "status": self.status,
            "sale_date_hint": normalize_sale_date(self.sale_date_hint),
        }


@dataclass
class CaseRecord:
    case_number: str
    rating: str
    title: str
    page_start: int
    page_end: int
    sale_date: date | None = None
    status: str | None = None
    pages: list[PageAnalysis] = field(default_factory=list)
    slide_segments: list[ImageSegment] = field(default_factory=list)
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


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _extract_top_left_cases_with_tesseract(rendered: RenderedPage) -> list[str]:
    ocr_map = tesseract_ocr_regions(
        rendered.image_path,
        [
            ("top_left", (0.0, 0.0, TOP_LEFT_X_RATIO, TOP_LEFT_Y_RATIO)),
            ("top_band", (0.0, 0.0, 0.85, 0.30)),
        ],
    )
    return _unique(
        extract_case_numbers((ocr_map.get("top_left") or "") + "\n" + (ocr_map.get("top_band") or ""))
    )


def _extract_page_case_numbers(rendered: RenderedPage) -> tuple[list[str], list[str]]:
    """(대표 사건번호들, 페이지 전체 표 시작 사건번호들) 반환."""
    layout = detect_page_layout(rendered)
    if layout is not None and layout.markers:
        page_cases = _unique([marker.case_number for marker in layout.markers])
        top_cases = _unique(
            [
                marker.case_number
                for marker in layout.markers
                if marker.x_left <= rendered.image_width * TOP_LEFT_X_RATIO
                and marker.y_top <= rendered.image_height * TOP_LEFT_Y_RATIO
            ]
        )
        return top_cases, page_cases

    top_cases = _extract_top_left_cases_with_tesseract(rendered)
    # layout이 없을 때는 과도한 분할을 피하기 위해 페이지 전체 case 목록은 대표 탐지값으로만 둔다.
    return _unique(top_cases), _unique(top_cases)


def analyze_page(rendered: RenderedPage, openai_api_key: str | None = None) -> PageAnalysis:
    text = extract_page_text(rendered.image_path, rendered.native_text, openai_api_key)

    top_case_numbers, page_case_numbers = _extract_page_case_numbers(rendered)

    region_ocr = tesseract_ocr_regions(
        rendered.image_path,
        [
            ("case", (0.0, 0.0, TOP_LEFT_X_RATIO, TOP_LEFT_Y_RATIO)),
            ("title", (0.0, 0.68, 1.0, 1.0)),
            ("sale", (0.35, 0.0, 1.0, 0.38)),
        ],
    )
    region_case_numbers = _unique(
        extract_case_numbers((region_ocr.get("case") or "") + "\n" + (region_ocr.get("sale") or ""))
    )
    if not top_case_numbers and region_case_numbers:
        top_case_numbers = list(region_case_numbers)
    if not page_case_numbers and region_case_numbers:
        page_case_numbers = list(region_case_numbers)

    title_candidates = extract_title_candidates(text)
    if not title_candidates:
        title_candidates = extract_title_candidates(region_ocr.get("title", ""))

    status = extract_progress_status(text) or extract_progress_status(region_ocr.get("sale", ""))
    sale_date_hint = parse_sale_date_from_text(text) or parse_sale_date_from_text(region_ocr.get("sale", ""))

    vision_payload = None
    needs_vision = (not top_case_numbers) or (len(page_case_numbers) > 1 and not top_case_numbers)
    if needs_vision and openai_api_key:
        try:
            vision_payload = openai_vision_case_metadata(rendered.image_path, openai_api_key)
        except Exception:
            vision_payload = None

        if vision_payload and vision_payload.case_number:
            if not top_case_numbers:
                top_case_numbers = [vision_payload.case_number]
            if not page_case_numbers:
                page_case_numbers = [vision_payload.case_number]
            elif len(page_case_numbers) > 1 and vision_payload.case_number in page_case_numbers:
                top_case_numbers = [vision_payload.case_number]

        if vision_payload and vision_payload.title and not title_candidates:
            title_candidates = extract_title_candidates(vision_payload.title) or [vision_payload.title]
        if vision_payload and vision_payload.sale_date and sale_date_hint is None:
            sale_date_hint = vision_payload.sale_date
        if vision_payload and vision_payload.status and not status:
            status = vision_payload.status

    if not top_case_numbers and openai_api_key:
        # 마지막 안전망: 사건번호 목록만 재질의
        try:
            top_case_numbers = _unique(openai_vision_case_numbers(rendered.image_path, openai_api_key))
        except Exception:
            top_case_numbers = []
        if top_case_numbers and not page_case_numbers:
            page_case_numbers = list(top_case_numbers)

    uncertain_source = "\n".join(
        [
            text,
            region_ocr.get("case", ""),
            region_ocr.get("sale", ""),
        ]
    )
    uncertain = looks_like_uncertain_case_marker(uncertain_source) if not top_case_numbers else False
    return PageAnalysis(
        page_no=rendered.page_no,
        case_numbers=top_case_numbers,
        page_case_numbers=page_case_numbers,
        rating=classify_rating(text),
        title_candidates=title_candidates,
        raw_text=text,
        image_path=rendered.image_path,
        uncertain_marker=uncertain,
        status=status,
        sale_date_hint=sale_date_hint,
    )


def _pick_title(pages: list[PageAnalysis], fallback: str) -> str:
    # 1순위: $$$ / SSS / $$+ 등이 있는 제목 라인
    for page in pages:
        for candidate in page.title_candidates:
            if len(candidate) >= MIN_TITLE_LENGTH and has_title_grade_marker(candidate):
                return candidate

    # 2순위: 일반 제목 후보
    for page in pages:
        for candidate in page.title_candidates:
            if len(candidate) >= MIN_TITLE_LENGTH:
                return candidate
    return fallback


def _pick_sale_date(pages: list[PageAnalysis]) -> date | None:
    for page in pages:
        if page.sale_date_hint is not None:
            return page.sale_date_hint
    for page in pages:
        found = parse_sale_date_from_text(page.raw_text)
        if found is not None:
            return found
    return None


def _pick_status(pages: list[PageAnalysis]) -> str | None:
    for page in pages:
        if page.status:
            return page.status
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
        if len(page.page_case_numbers) > 1:
            for case_no in page.page_case_numbers:
                record = CaseRecord(
                    case_number=case_no,
                    rating=RATING_UNKNOWN,
                    title="",
                    page_start=page.page_no,
                    page_end=page.page_no,
                    pages=[page],
                )
                records.append(record)
            current = records[-1]
            continue

        found = page.case_numbers[0] if page.case_numbers else None

        if found is not None:
            if current is None or found != current.case_number:
                current = CaseRecord(
                    case_number=found,
                    rating=RATING_UNKNOWN,
                    title="",
                    page_start=page.page_no,
                    page_end=page.page_no,
                )
                records.append(current)

            current.pages.append(page)
            current.page_end = page.page_no
            continue

        # 사건번호 없는 페이지는 "직전 사건 + 연속 페이지"일 때만 붙인다.
        if current is not None and page.page_no == current.page_end + 1:
            current.pages.append(page)
            current.page_end = page.page_no

    for record in records:
        record.rating = _pick_rating_label(record.pages)
        record.title = _pick_title(record.pages, fallback=record.case_number)
        record.sale_date = _pick_sale_date(record.pages)
        record.status = _pick_status(record.pages)

    return records


def split_uncertain_continuations(
    records: list[CaseRecord],
) -> tuple[list[CaseRecord], list[PageAnalysis]]:
    """사건번호가 불확실한 페이지는 직전 사건에 붙이지 않고 검토필요로 분리한다."""
    review_pages: list[PageAnalysis] = []
    cleaned_records: list[CaseRecord] = []

    for record in records:
        kept_pages: list[PageAnalysis] = []
        for page in record.pages:
            if not page.case_numbers and page.uncertain_marker:
                review_pages.append(page)
                continue
            kept_pages.append(page)

        if not kept_pages:
            continue

        record.pages = kept_pages
        record.page_start = min(p.page_no for p in kept_pages)
        record.page_end = max(p.page_no for p in kept_pages)
        cleaned_records.append(record)

    return cleaned_records, review_pages


def assign_image_segments(
    records: list[CaseRecord],
    rendered_pages: list[RenderedPage],
    analyses: list[PageAnalysis],
    work_dir: Path,
) -> list[ImageSegment]:
    rendered_by_page = {r.page_no: r for r in rendered_pages}

    # 같은 페이지 안에 사건번호가 여러 개면 해당 페이지는 표 시작 y 기준으로 크게 분할한다.
    page_segments: dict[int, list[ImageSegment]] = {}
    review_segments: list[ImageSegment] = []
    for analysis in analyses:
        if len(analysis.page_case_numbers) <= 1:
            continue

        rendered = rendered_by_page.get(analysis.page_no)
        if rendered is None:
            continue

        segments = segment_page(rendered, analysis.page_case_numbers, work_dir)
        page_segments[analysis.page_no] = segments
        review_segments.extend([seg for seg in segments if seg.is_review or seg.case_number == REVIEW_LABEL])

    for record in records:
        slides: list[ImageSegment] = []
        for page in record.pages:
            rendered = rendered_by_page.get(page.page_no)
            if rendered is None:
                continue

            mixed_segments = page_segments.get(page.page_no)
            if mixed_segments is not None:
                matched = [
                    seg
                    for seg in mixed_segments
                    if seg.case_number == record.case_number and not seg.is_review
                ]
                slides.extend(matched)
                continue

            slides.append(
                ImageSegment(
                    case_number=record.case_number,
                    page_no=page.page_no,
                    image_path=rendered.image_path,
                    from_mixed_page=False,
                    order_index=1,
                )
            )

        slides.sort(key=lambda s: (s.page_no, s.order_index))
        for seg in slides:
            if not seg.source_refs:
                if seg.from_mixed_page:
                    seg.source_refs = [f"p{seg.page_no} crop{seg.order_index}"]
                else:
                    seg.source_refs = [f"p{seg.page_no}"]

        record.slide_segments = slides
        record.image_segments = compose_slides_into_bundles(record.case_number, slides, work_dir)

    # 분할 실패로 REVIEW로 빠진 페이지는 어떤 사건에도 섞지 않는다.
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
