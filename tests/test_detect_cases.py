from pathlib import Path

from husik.pdf.detect_cases import PageAnalysis, group_pages_into_cases

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
