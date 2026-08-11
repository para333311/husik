from pathlib import Path

from PIL import Image

import husik.pdf.detect_cases as detect_module
from husik.pdf.detect_cases import (
    CASE_CONFIDENT_THRESHOLD,
    CASE_REVIEW_THRESHOLD,
    PageAnalysis,
    analyze_page,
    group_pages_into_cases,
)
from husik.pdf.ocr import VisionCaseResult
from husik.pdf.render import RenderedPage
from husik.vision.base import CaseBlock, PageVisionResult, VisionProvider

RATING_UNKNOWN = "등급확인"


class StubVisionProvider(VisionProvider):
    provider_name = "stub"

    def __init__(self, result: PageVisionResult | None):
        self.result = result
        self.calls = 0

    @property
    def enabled(self) -> bool:
        return True

    @property
    def model_name(self) -> str:
        return "stub-model"

    def analyze_page(self, image_path: Path, page_no: int, work_dir: Path) -> PageVisionResult | None:
        self.calls += 1
        return self.result


def _page(
    page_no,
    case_numbers=None,
    page_case_numbers=None,
    rating=RATING_UNKNOWN,
    title_candidates=None,
    text="",
    status=None,
):
    reps = case_numbers or []
    return PageAnalysis(
        page_no=page_no,
        case_numbers=reps,
        page_case_numbers=page_case_numbers if page_case_numbers is not None else list(reps),
        rating=rating,
        title_candidates=title_candidates or [],
        raw_text=text,
        image_path=Path(f"/tmp/page_{page_no}.jpg"),
        status=status,
    )


def _rendered(tmp_path: Path, page_no: int = 1, text: str = "") -> RenderedPage:
    image_path = tmp_path / f"page_{page_no:03d}.jpg"
    Image.new("RGB", (900, 1400), "white").save(image_path)
    return RenderedPage(
        page_no=page_no,
        image_path=image_path,
        native_text=text,
        image_width=900,
        image_height=1400,
    )


def test_pages_without_case_number_are_not_auto_attached():
    pages = [
        _page(1, case_numbers=["2025타경1708"], rating="$$$", title_candidates=["효창공원 시프트 SSS"]),
        _page(2, case_numbers=[]),
        _page(3, case_numbers=[]),
        _page(4, case_numbers=["2025타경2000"], rating="$$$$", title_candidates=["다음 사건 $$$"]),
    ]

    records = group_pages_into_cases(pages)

    assert [r.case_number for r in records] == ["2025타경1708", "2025타경2000"]
    assert (records[0].page_start, records[0].page_end) == (1, 1)
    assert (records[1].page_start, records[1].page_end) == (4, 4)


def test_body_case_number_without_representative_is_not_used_as_case_start():
    pages = [
        _page(1, case_numbers=["2025타경1708"], title_candidates=["효창공원 시프트 $$$"]),
        _page(2, case_numbers=[], page_case_numbers=["2016타경7487"], text="본문 과거 사건번호 2016타경7487"),
        _page(3, case_numbers=[]),
    ]

    records = group_pages_into_cases(pages)

    assert len(records) == 1
    assert records[0].case_number == "2025타경1708"
    assert records[0].page_end == 1


def test_non_consecutive_pages_without_case_number_are_not_attached():
    pages = [
        _page(1, case_numbers=["2025타경1708"], title_candidates=["효창공원 시프트 $$$"]),
        _page(3, case_numbers=[]),
        _page(4, case_numbers=["2025타경2000"], title_candidates=["다음 사건 $$$"]),
    ]

    records = group_pages_into_cases(pages)

    assert len(records) == 2
    assert (records[0].page_start, records[0].page_end) == (1, 1)
    assert (records[1].page_start, records[1].page_end) == (4, 4)


def test_status_is_picked_from_detected_case_page():
    pages = [
        _page(1, case_numbers=["2025타경1708"], title_candidates=["효창공원 시프트 $$$"], status="낙찰"),
    ]

    records = group_pages_into_cases(pages)
    assert records[0].status == "낙찰"


def test_title_prefers_lines_with_grade_marker():
    pages = [
        _page(
            1,
            case_numbers=["2025타경1708"],
            title_candidates=["일반 설명 텍스트", "효창공원 시프트 SSS"],
        )
    ]

    records = group_pages_into_cases(pages)
    assert records[0].title == "효창공원 시프트 SSS"


def test_title_falls_back_to_case_number_when_no_candidates():
    pages = [_page(1, case_numbers=["2024타경1234"], title_candidates=[])]
    records = group_pages_into_cases(pages)
    assert records[0].title == "2024타경1234"


def test_analyze_page_calls_openai_fallback_when_case_missing_and_explicitly_enabled(tmp_path, monkeypatch):
    rendered = _rendered(tmp_path, 1, text="")

    monkeypatch.setattr(detect_module, "extract_page_text", lambda *_: "")
    monkeypatch.setattr(detect_module, "_extract_page_case_numbers", lambda *_: ([], []))
    monkeypatch.setattr(
        detect_module,
        "tesseract_ocr_regions",
        lambda *_args, **_kwargs: {"case": "", "title": "", "sale": ""},
    )

    called = {"vision": 0}

    def _vision(*_args, **_kwargs):
        called["vision"] += 1
        return VisionCaseResult(
            is_case_start=True,
            case_number="2025타경1708",
            title="효창공원 시프트 SSS",
            confidence=0.92,
        )

    monkeypatch.setattr(detect_module, "openai_vision_case_metadata", _vision)

    analysis = analyze_page(rendered, openai_api_key="dummy", openai_vision_enabled=True)

    assert called["vision"] == 1
    assert analysis.case_numbers == ["2025타경1708"]
    assert analysis.source == "openai_fallback"


def test_analyze_page_does_not_call_openai_when_disabled_even_if_api_key_exists(tmp_path, monkeypatch):
    rendered = _rendered(tmp_path, 1, text="")

    monkeypatch.setattr(detect_module, "extract_page_text", lambda *_: "")
    monkeypatch.setattr(detect_module, "_extract_page_case_numbers", lambda *_: ([], []))
    monkeypatch.setattr(
        detect_module,
        "tesseract_ocr_regions",
        lambda *_args, **_kwargs: {"case": "", "title": "", "sale": ""},
    )

    called = {"vision": 0}

    def _vision(*_args, **_kwargs):
        called["vision"] += 1
        return VisionCaseResult(case_number="2025타경1708")

    monkeypatch.setattr(detect_module, "openai_vision_case_metadata", _vision)

    analysis = analyze_page(rendered, openai_api_key="dummy", openai_vision_enabled=False)

    assert called["vision"] == 0
    assert analysis.case_numbers == []
    assert analysis.source == "ocr_fallback"


def test_analyze_page_uses_gemini_result_over_ocr(tmp_path, monkeypatch):
    rendered = _rendered(tmp_path, 1, text="2025타경9999")

    monkeypatch.setattr(detect_module, "extract_page_text", lambda *_: "2025타경9999")
    monkeypatch.setattr(
        detect_module,
        "_extract_page_case_numbers",
        lambda *_: (["2025타경9999"], ["2025타경9999"]),
    )

    provider = StubVisionProvider(
        PageVisionResult(
            case_blocks=[
                CaseBlock(
                    case_number="2025타경1708",
                    confidence=CASE_CONFIDENT_THRESHOLD,
                    y_top=0.1,
                    y_bottom=0.7,
                    title="효창공원 시프트 SSS",
                )
            ],
            review_required=False,
            source="gemini",
        )
    )

    called = {"openai": 0}

    def _openai_meta(*_args, **_kwargs):
        called["openai"] += 1
        return VisionCaseResult(case_number="2025타경0001")

    monkeypatch.setattr(detect_module, "openai_vision_case_metadata", _openai_meta)

    analysis = analyze_page(
        rendered,
        openai_api_key="dummy",
        openai_vision_enabled=True,
        vision_provider=provider,
        work_dir=tmp_path,
        pdf_hash="pdf",
    )

    assert analysis.case_numbers == ["2025타경1708"]
    assert analysis.source.startswith("gemini")
    assert called["openai"] == 0


def test_gemini_failure_does_not_fallback_to_openai_even_when_enabled(tmp_path, monkeypatch):
    rendered = _rendered(tmp_path, 1, text="")

    monkeypatch.setattr(detect_module, "extract_page_text", lambda *_: "")
    monkeypatch.setattr(detect_module, "_extract_page_case_numbers", lambda *_: ([], []))
    monkeypatch.setattr(
        detect_module,
        "tesseract_ocr_regions",
        lambda *_args, **_kwargs: {"case": "", "title": "", "sale": ""},
    )

    provider = StubVisionProvider(None)
    called = {"openai": 0}

    def _openai_meta(*_args, **_kwargs):
        called["openai"] += 1
        return VisionCaseResult(case_number="2025타경1234")

    monkeypatch.setattr(detect_module, "openai_vision_case_metadata", _openai_meta)

    analysis = analyze_page(
        rendered,
        openai_api_key="dummy",
        openai_vision_enabled=True,
        vision_provider=provider,
        work_dir=tmp_path,
        pdf_hash="pdf",
    )

    assert called["openai"] == 0
    assert analysis.case_numbers == []
    assert analysis.source == "ocr_fallback"


def test_analyze_page_low_confidence_routes_to_review(tmp_path, monkeypatch):
    rendered = _rendered(tmp_path, 1, text="")

    monkeypatch.setattr(detect_module, "extract_page_text", lambda *_: "")

    provider = StubVisionProvider(
        PageVisionResult(
            case_blocks=[
                CaseBlock(
                    case_number="2025타경1708",
                    confidence=(CASE_REVIEW_THRESHOLD + CASE_CONFIDENT_THRESHOLD) / 2,
                    y_top=0.2,
                    y_bottom=0.8,
                )
            ],
            review_required=False,
            source="gemini",
        )
    )

    analysis = analyze_page(rendered, vision_provider=provider, work_dir=tmp_path, pdf_hash="pdf")

    assert analysis.case_numbers == []
    assert analysis.review_reason == "case number unclear"
    assert analysis.uncertain_marker is True


def test_analyze_page_works_without_openai_key(tmp_path, monkeypatch):
    rendered = _rendered(tmp_path, 1, text="2025 타경 1708")

    monkeypatch.setattr(
        detect_module,
        "_extract_page_case_numbers",
        lambda *_: (["2025타경1708"], ["2025타경1708"]),
    )

    analysis = analyze_page(rendered, openai_api_key=None)

    assert analysis.case_numbers == ["2025타경1708"]
