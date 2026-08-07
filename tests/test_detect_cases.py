from pathlib import Path

from PIL import Image

import husik.pdf.detect_cases as detect_module
from husik.pdf.detect_cases import PageAnalysis, analyze_page, group_pages_into_cases
from husik.pdf.ocr import VisionCaseResult
from husik.pdf.render import RenderedPage

RATING_UNKNOWN = "등급확인"


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


def test_top_left_representative_case_numbers_split_ranges():
    pages = [
        _page(1, case_numbers=["2025타경1708"], rating="$$$", title_candidates=["효창공원 시프트 SSS"]),
        _page(2, case_numbers=[]),
        _page(3, case_numbers=[]),
        _page(4, case_numbers=["2025타경2000"], rating="$$$$", title_candidates=["다음 사건 $$$"]),
    ]

    records = group_pages_into_cases(pages)

    assert [r.case_number for r in records] == ["2025타경1708", "2025타경2000"]
    assert (records[0].page_start, records[0].page_end) == (1, 3)
    assert (records[1].page_start, records[1].page_end) == (4, 4)


def test_body_case_number_without_representative_is_ignored_for_start_signal():
    pages = [
        _page(1, case_numbers=["2025타경1708"], title_candidates=["효창공원 시프트 $$$"]),
        _page(2, case_numbers=[], page_case_numbers=["2016타경7487"], text="본문 과거 사건번호 2016타경7487"),
        _page(3, case_numbers=[]),
    ]

    records = group_pages_into_cases(pages)

    assert len(records) == 1
    assert records[0].case_number == "2025타경1708"
    assert records[0].page_end == 3


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


def test_status_is_picked_from_case_pages():
    pages = [
        _page(1, case_numbers=["2025타경1708"], title_candidates=["효창공원 시프트 $$$"]),
        _page(2, case_numbers=[], status="낙찰"),
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
    pages = [_page(1, case_numbers=["2024타경1"], title_candidates=[])]
    records = group_pages_into_cases(pages)
    assert records[0].title == "2024타경1"


def test_uncertain_page_is_split_to_review_not_attached():
    pages = [
        _page(1, case_numbers=["2025타경1708"], title_candidates=["효창공원 시프트 SSS"]),
        _page(2, case_numbers=[], text="2025타경", status=None),
    ]
    pages[1].uncertain_marker = True

    records, review_pages = detect_module.split_uncertain_continuations(group_pages_into_cases(pages))

    assert len(records) == 1
    assert records[0].page_end == 1
    assert [p.page_no for p in review_pages] == [2]


def test_analyze_page_calls_vision_fallback_when_case_missing(tmp_path, monkeypatch):
    image_path = tmp_path / "page.jpg"
    Image.new("RGB", (800, 1200), "white").save(image_path)
    rendered = RenderedPage(
        page_no=1,
        image_path=image_path,
        native_text="",
        image_width=800,
        image_height=1200,
    )

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

    analysis = analyze_page(rendered, openai_api_key="dummy")

    assert called["vision"] == 1
    assert analysis.case_numbers == ["2025타경1708"]


def test_analyze_page_vision_failure_does_not_crash(tmp_path, monkeypatch):
    image_path = tmp_path / "page.jpg"
    Image.new("RGB", (800, 1200), "white").save(image_path)
    rendered = RenderedPage(
        page_no=1,
        image_path=image_path,
        native_text="",
        image_width=800,
        image_height=1200,
    )

    monkeypatch.setattr(detect_module, "extract_page_text", lambda *_: "")
    monkeypatch.setattr(detect_module, "_extract_page_case_numbers", lambda *_: ([], []))
    monkeypatch.setattr(
        detect_module,
        "tesseract_ocr_regions",
        lambda *_args, **_kwargs: {"case": "", "title": "", "sale": ""},
    )
    monkeypatch.setattr(
        detect_module,
        "openai_vision_case_metadata",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("vision down")),
    )
    monkeypatch.setattr(detect_module, "openai_vision_case_numbers", lambda *_args, **_kwargs: [])

    analysis = analyze_page(rendered, openai_api_key="dummy")

    assert analysis.case_numbers == []


def test_analyze_page_works_without_openai_key(tmp_path, monkeypatch):
    image_path = tmp_path / "page.jpg"
    Image.new("RGB", (800, 1200), "white").save(image_path)
    rendered = RenderedPage(
        page_no=1,
        image_path=image_path,
        native_text="2025 타경 1708",
        image_width=800,
        image_height=1200,
    )

    monkeypatch.setattr(
        detect_module,
        "_extract_page_case_numbers",
        lambda *_: (["2025타경1708"], ["2025타경1708"]),
    )

    analysis = analyze_page(rendered, openai_api_key=None)

    assert analysis.case_numbers == ["2025타경1708"]
