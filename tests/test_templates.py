from datetime import date

from husik.telegram.templates import (
    AuctionFields,
    CaseMessageData,
    InterestStats,
    build_award_update,
    build_event_update,
    build_representative_message,
    truncate_message,
)


def test_representative_message_header_unknown_date():
    data = CaseMessageData(case_number="2024타경12345", rating="$$$$", title="강남 아파트 특급매물")
    text = build_representative_message(data)
    assert text.startswith("[입찰일 확인중] $$$$ 강남 아파트 특급매물")
    assert "출처: 매수맛집" not in text
    assert "PDF 첨부" not in text


def test_representative_message_header_with_sale_date():
    data = CaseMessageData(
        case_number="2024타경12345",
        rating="$$$$",
        title="강남 아파트 특급매물",
        auction=AuctionFields(sale_date=date(2026, 8, 20)),
    )
    text = build_representative_message(data)
    assert text.startswith("[2026-08-20 입찰 D-")
    assert "$$$$ 강남 아파트 특급매물" in text.splitlines()[0]


def test_representative_message_contains_required_fields():
    data = CaseMessageData(
        case_number="2024타경12345",
        rating="$$$$",
        title="제목",
        interest=InterestStats(court_views=10, madangs_views=5, blog_mentions=2, recent_blog_mentions=1),
    )
    text = build_representative_message(data)
    for field in [
        "사건번호:",
        "물건번호:",
        "법원:",
        "소재지:",
        "감정가:",
        "최저가:",
        "매각기일:",
        "상태:",
        "관심도:",
        "법원경매 조회수:",
        "경매마당 조회수:",
        "블로그 언급:",
        "최근 7일 신규 블로그:",
        "경매마당 링크:",
        "법원경매 링크:",
    ]:
        assert field in text


def test_event_update_prepends_new_block_above_existing():
    data = CaseMessageData(case_number="2024타경12345", rating="$$$$", title="제목")
    updated = build_event_update("블로그업데이트", data, existing_message="옛날 대표 메시지")
    assert updated.startswith("[블로그업데이트]")
    assert updated.index("블로그업데이트") < updated.index("옛날 대표 메시지")
    assert "기존 내용" in updated


def test_award_update_includes_bidder_count():
    data = CaseMessageData(
        case_number="2024타경12345",
        rating="$$$$",
        title="제목",
        auction=AuctionFields(winning_price=550_000_000, winning_rate=91.2, bidder_count=7),
    )
    updated = build_award_update(data, existing_message="이전 내용")
    assert "낙찰결과" in updated
    assert "입찰인수: 7명" in updated
    assert "낙찰가: 550,000,000원" in updated
    assert "낙찰가율: 91.2%" in updated


def test_truncate_message_respects_limit():
    long_text = "가" * 5000
    truncated = truncate_message(long_text, limit=100)
    assert len(truncated) <= 130
    assert truncated != long_text


def test_representative_message_header_low_grade_uses_brackets():
    data = CaseMessageData(case_number="2024타경1", rating="낮은등급", title="제목")
    text = build_representative_message(data)
    assert text.startswith("[입찰일 확인중] [낮은등급] 제목")


def test_representative_message_header_grade_unknown_uses_brackets():
    data = CaseMessageData(case_number="2024타경1", rating="등급확인", title="제목")
    text = build_representative_message(data)
    assert text.startswith("[입찰일 확인중] [등급확인] 제목")


def test_representative_message_header_dollar_rating_not_bracketed():
    data = CaseMessageData(case_number="2024타경1", rating="$$$", title="사당 15 추천 $$$")
    text = build_representative_message(data)
    assert text.startswith("[입찰일 확인중] $$$ 사당 15 추천 $$$")
    assert "[$$$]" not in text
