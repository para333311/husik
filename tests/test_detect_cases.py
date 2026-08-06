from pathlib import Path

from husik.pdf.detect_cases import PageAnalysis, filter_qualified_cases, group_pages_into_cases


def _page(page_no, case_numbers=None, rating=None, title_candidates=None, text=""):
    return PageAnalysis(
        page_no=page_no,
        case_numbers=case_numbers or [],
        rating=rating,
        title_candidates=title_candidates or [],
        raw_text=text,
        image_path=Path(f"/tmp/page_{page_no}.jpg"),
    )


def test_repeated_dollar_signs_do_not_split_case():
    pages = [
        _page(1, case_numbers=["2024타경12345"], rating="$$$$", title_candidates=["강남 아파트"]),
        _page(2, case_numbers=["2024타경12345"], rating=None),
        _page(3, case_numbers=["2024타경12345"], rating="$$$$"),  # repeated $$$$, still same case
    ]
    records = group_pages_into_cases(pages)
    assert len(records) == 1
    assert records[0].case_number == "2024타경12345"
    assert records[0].page_start == 1
    assert records[0].page_end == 3
    assert records[0].rating == "$$$$"
    assert records[0].title == "강남 아파트"


def test_page_without_case_number_joins_previous_case():
    pages = [
        _page(1, case_numbers=["2024타경1"], rating="$$$$", title_candidates=["매물A"]),
        _page(2, case_numbers=[]),  # no case number, belongs to case 1
        _page(3, case_numbers=["2024타경2"], rating="$$$$", title_candidates=["매물B"]),
    ]
    records = group_pages_into_cases(pages)
    assert len(records) == 2
    assert records[0].case_number == "2024타경1"
    assert records[0].page_start == 1
    assert records[0].page_end == 2
    assert records[1].case_number == "2024타경2"
    assert records[1].page_start == 3
    assert records[1].page_end == 3


def test_pages_before_first_case_number_are_dropped():
    pages = [
        _page(1, case_numbers=[]),
        _page(2, case_numbers=["2024타경1"], rating="$$$$", title_candidates=["매물A"]),
    ]
    records = group_pages_into_cases(pages)
    assert len(records) == 1
    assert records[0].page_start == 2


def test_filter_qualified_cases_drops_below_three_dollars():
    pages = [
        _page(1, case_numbers=["2024타경1"], rating="$$", title_candidates=["매물A"]),
        _page(2, case_numbers=["2024타경2"], rating="$$$", title_candidates=["매물B"]),
        _page(3, case_numbers=["2024타경3"], rating=None, title_candidates=["매물C"]),
        _page(4, case_numbers=["2024타경4"], rating="$$$$", title_candidates=["매물D"]),
    ]
    records = group_pages_into_cases(pages)
    qualified = filter_qualified_cases(records)
    qualified_numbers = {r.case_number for r in qualified}
    assert qualified_numbers == {"2024타경2", "2024타경4"}


def test_title_falls_back_to_case_number_when_no_candidates():
    pages = [_page(1, case_numbers=["2024타경1"], rating="$$$$", title_candidates=[])]
    records = group_pages_into_cases(pages)
    assert records[0].title == "2024타경1"


def test_rating_only_considered_near_case_start():
    # rating appears far beyond the lookahead window; should not be picked up
    pages = [
        _page(1, case_numbers=["2024타경1"], rating=None, title_candidates=["매물A"]),
        _page(2, case_numbers=["2024타경1"], rating=None),
        _page(3, case_numbers=["2024타경1"], rating=None),
        _page(4, case_numbers=["2024타경1"], rating="$$$$"),  # beyond RATING_LOOKAHEAD_PAGES=3
    ]
    records = group_pages_into_cases(pages)
    assert records[0].rating is None
    assert filter_qualified_cases(records) == []
