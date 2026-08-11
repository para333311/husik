"""사건표 기준으로 페이지를 사건 단위로 묶고, 사건별 슬라이드를 번들 이미지로 합성한다."""
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
    crop_band,
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
from husik.vision.base import CaseBlock, PageVisionResult, VisionCache, VisionProvider
from husik.vision.gemini import GeminiVisionProvider, build_contact_sheet

TOP_LEFT_X_RATIO = 0.45
TOP_LEFT_Y_RATIO = 0.25
RATING_LOOKAHEAD_PAGES = 3
MIN_TITLE_LENGTH = 4
CASE_CONFIDENT_THRESHOLD = 0.75
CASE_REVIEW_THRESHOLD = 0.55
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
    source: str = "fallback"
    confidence: float = 0.0
    vision_blocks: list[CaseBlock] = field(default_factory=list)
    review_reason: str | None = None

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
            "source": self.source,
            "confidence": self.confidence,
            "review_reason": self.review_reason,
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


@dataclass
class AnalyzedPdf:
    records: list[CaseRecord]
    analyses: list[PageAnalysis] = field(default_factory=list)
    review_segments: list[ImageSegment] = field(default_factory=list)


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
    return _unique(top_cases), _unique(top_cases)


def _pick_primary_block(blocks: list[CaseBlock]) -> CaseBlock | None:
    if not blocks:
        return None
    return sorted(blocks, key=lambda b: (-b.confidence, b.y_top))[0]


def _analyze_with_gemini(
    rendered: RenderedPage,
    vision_provider: VisionProvider | None,
    vision_cache: VisionCache | None,
    pdf_hash: str,
    work_dir: Path | None,
) -> PageVisionResult | None:
    if vision_provider is None or not vision_provider.enabled:
        return None
    if work_dir is None:
        return None

    provider_image = rendered.image_path
    if isinstance(vision_provider, GeminiVisionProvider):
        provider_image = build_contact_sheet(rendered, work_dir)

    image_hash = VisionCache.hash_file(provider_image)
    key = VisionCache.build_key(
        pdf_hash=pdf_hash,
        page_no=rendered.page_no,
        image_hash=image_hash,
        provider_name=vision_provider.provider_name,
        model_name=vision_provider.model_name,
    )

    if vision_cache is not None:
        cached = vision_cache.get(key)
        if cached is not None:
            cached.source = "gemini(cache)"
            return cached

    result = vision_provider.analyze_page(provider_image, rendered.page_no, work_dir)
    if result is None:
        return None

    result.source = "gemini"
    if vision_cache is not None:
        vision_cache.set(key, result)
        vision_cache.save()
    return result


def analyze_page(
    rendered: RenderedPage,
    openai_api_key: str | None = None,
    vision_provider: VisionProvider | None = None,
    vision_cache: VisionCache | None = None,
    pdf_hash: str = "",
    work_dir: Path | None = None,
) -> PageAnalysis:
    # Vision-first: 사건번호 판정은 Gemini를 우선으로 시도한다.
    vision_result = _analyze_with_gemini(rendered, vision_provider, vision_cache, pdf_hash, work_dir)
    vision_blocks = vision_result.case_blocks if vision_result else []

    # OCR/PDF text layer는 title/date/status 보조와 fallback에 사용한다.
    text = extract_page_text(rendered.image_path, rendered.native_text, openai_api_key)

    confirmed_blocks = [
        block for block in vision_blocks if block.confidence >= CASE_CONFIDENT_THRESHOLD and block.case_number
    ]

    if confirmed_blocks:
        page_case_numbers = _unique(
            [block.case_number for block in sorted(confirmed_blocks, key=lambda b: b.y_top)]
        )
        top_case_numbers = list(page_case_numbers)
        primary = _pick_primary_block(confirmed_blocks)

        title_candidates = [block.title for block in confirmed_blocks if block.title]
        title_candidates.extend(extract_title_candidates(text))
        sale_date_hint = None
        if primary and primary.sale_date:
            try:
                y, m, d = primary.sale_date.split(".")
                sale_date_hint = date(int(y), int(m), int(d))
            except Exception:
                sale_date_hint = parse_sale_date_from_text(text)
        else:
            sale_date_hint = parse_sale_date_from_text(text)

        status = (primary.status if primary else None) or extract_progress_status(text)
        confidence = max(block.confidence for block in confirmed_blocks)

        return PageAnalysis(
            page_no=rendered.page_no,
            case_numbers=top_case_numbers,
            page_case_numbers=page_case_numbers,
            rating=classify_rating(text),
            title_candidates=_unique([x for x in title_candidates if x]),
            raw_text=text,
            image_path=rendered.image_path,
            uncertain_marker=False,
            status=status,
            sale_date_hint=sale_date_hint,
            source=vision_result.source if vision_result else "gemini",
            confidence=confidence,
            vision_blocks=vision_blocks,
            review_reason=(
                "case number unclear" if vision_result and vision_result.review_required else None
            ),
        )

    # Gemini가 켜져 있고 사건 후보를 봤지만 신뢰도가 낮으면 fallback으로 억지 연결하지 않는다.
    if vision_result is not None:
        review_blocks = [
            block
            for block in vision_blocks
            if block.case_number and block.confidence >= CASE_REVIEW_THRESHOLD
        ]
        if vision_result.review_required or review_blocks:
            return PageAnalysis(
                page_no=rendered.page_no,
                case_numbers=[],
                page_case_numbers=[],
                rating=classify_rating(text),
                title_candidates=extract_title_candidates(text),
                raw_text=text,
                image_path=rendered.image_path,
                uncertain_marker=True,
                status=extract_progress_status(text),
                sale_date_hint=parse_sale_date_from_text(text),
                source=vision_result.source,
                confidence=max([block.confidence for block in vision_blocks], default=0.0),
                vision_blocks=vision_blocks,
                review_reason="case number unclear",
            )

    # fallback: PDF text layer + tesseract + OpenAI case metadata
    top_case_numbers, page_case_numbers = _extract_page_case_numbers(rendered)

    region_ocr = tesseract_ocr_regions(
        rendered.image_path,
        [
            ("case", (0.0, 0.0, TOP_LEFT_X_RATIO, TOP_LEFT_Y_RATIO)),
            ("title", (0.0, 0.0, 1.0, 1.0)),
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

    if not top_case_numbers and openai_api_key:
        try:
            fallback_meta = openai_vision_case_metadata(rendered.image_path, openai_api_key)
            if fallback_meta.case_number:
                top_case_numbers = [fallback_meta.case_number]
                page_case_numbers = [fallback_meta.case_number]
            if fallback_meta.title and not title_candidates:
                title_candidates = [fallback_meta.title]
            if fallback_meta.sale_date and sale_date_hint is None:
                sale_date_hint = fallback_meta.sale_date
            if fallback_meta.status and not status:
                status = fallback_meta.status
        except Exception:
            pass

    if not top_case_numbers and openai_api_key:
        try:
            top_case_numbers = _unique(openai_vision_case_numbers(rendered.image_path, openai_api_key))
            if top_case_numbers and not page_case_numbers:
                page_case_numbers = list(top_case_numbers)
        except Exception:
            top_case_numbers = []

    uncertain_source = "\n".join([text, region_ocr.get("case", ""), region_ocr.get("sale", "")])
    uncertain = looks_like_uncertain_case_marker(uncertain_source) if not top_case_numbers else False
    review_reason = "case number unclear" if (uncertain and not top_case_numbers) else None

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
        source="ocr_fallback",
        confidence=0.0,
        vision_blocks=[],
        review_reason=review_reason,
    )


def _pick_title(pages: list[PageAnalysis], fallback: str) -> str:
    for page in pages:
        for candidate in page.title_candidates:
            if len(candidate) >= MIN_TITLE_LENGTH and has_title_grade_marker(candidate):
                return candidate

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

        # 사건번호 없는 페이지는 직전 사건에 자동 첨부하지 않는다(혼합 방지 우선).
        current = current

    for record in records:
        record.rating = _pick_rating_label(record.pages)
        record.title = _pick_title(record.pages, fallback=record.case_number)
        record.sale_date = _pick_sale_date(record.pages)
        record.status = _pick_status(record.pages)

    return records


def split_uncertain_continuations(records: list[CaseRecord]) -> tuple[list[CaseRecord], list[PageAnalysis]]:
    review_pages: list[PageAnalysis] = []
    cleaned_records: list[CaseRecord] = []

    for record in records:
        kept_pages: list[PageAnalysis] = []
        for page in record.pages:
            if not page.case_numbers and (page.uncertain_marker or page.review_reason):
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


def _segment_page_with_vision_blocks(
    rendered: RenderedPage,
    analysis: PageAnalysis,
    work_dir: Path,
) -> list[ImageSegment]:
    confident_blocks = [
        block
        for block in analysis.vision_blocks
        if block.case_number and block.confidence >= CASE_CONFIDENT_THRESHOLD
    ]
    if len(confident_blocks) <= 1:
        return []

    segments: list[ImageSegment] = []
    for i, block in enumerate(sorted(confident_blocks, key=lambda b: b.y_top), start=1):
        y_top = int(rendered.image_height * max(0.0, min(1.0, block.y_top)))
        y_bottom = int(rendered.image_height * max(0.0, min(1.0, block.y_bottom)))
        if y_bottom <= y_top:
            y_bottom = min(rendered.image_height, y_top + 20)
        crop_path = work_dir / f"page_{rendered.page_no:03d}_vision_crop{i:02d}.jpg"
        crop_band(rendered.image_path, y_top, y_bottom, crop_path)
        segments.append(
            ImageSegment(
                case_number=block.case_number,
                page_no=rendered.page_no,
                image_path=crop_path,
                from_mixed_page=True,
                order_index=i,
                source_refs=[f"p{rendered.page_no} crop{i}"],
            )
        )
    return segments


def assign_image_segments(
    records: list[CaseRecord],
    rendered_pages: list[RenderedPage],
    analyses: list[PageAnalysis],
    work_dir: Path,
) -> list[ImageSegment]:
    rendered_by_page = {r.page_no: r for r in rendered_pages}

    page_segments: dict[int, list[ImageSegment]] = {}
    review_segments: list[ImageSegment] = []
    for analysis in analyses:
        if len(analysis.page_case_numbers) <= 1:
            continue

        rendered = rendered_by_page.get(analysis.page_no)
        if rendered is None:
            continue

        vision_segments = _segment_page_with_vision_blocks(rendered, analysis, work_dir)
        segments = vision_segments or segment_page(rendered, analysis.page_case_numbers, work_dir)
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
                seg.source_refs = [
                    f"p{seg.page_no} crop{seg.order_index}"
                    if seg.from_mixed_page
                    else f"p{seg.page_no}"
                ]

        record.slide_segments = slides
        record.image_segments = compose_slides_into_bundles(record.case_number, slides, work_dir)

    return review_segments


def analyze_pdf_pages(
    rendered_pages: list[RenderedPage],
    analyses: list[PageAnalysis],
    work_dir: Path,
) -> AnalyzedPdf:
    records = group_pages_into_cases(analyses)
    records, review_pages = split_uncertain_continuations(records)
    review_segments = assign_image_segments(records, rendered_pages, analyses, work_dir)

    reviewed_page_nos = {seg.page_no for seg in review_segments}
    for analysis in analyses:
        if analysis.review_reason and analysis.page_no not in reviewed_page_nos:
            review_segments.append(
                ImageSegment(
                    case_number=REVIEW_LABEL,
                    page_no=analysis.page_no,
                    image_path=analysis.image_path,
                    is_review=True,
                    source_refs=[f"p{analysis.page_no}"],
                )
            )

    for page in review_pages:
        review_segments.append(
            ImageSegment(
                case_number=REVIEW_LABEL,
                page_no=page.page_no,
                image_path=page.image_path,
                is_review=True,
                source_refs=[f"p{page.page_no}"],
            )
        )

    return AnalyzedPdf(records=records, analyses=analyses, review_segments=review_segments)
