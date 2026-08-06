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
    assert text.startswith("[입찰일 확인중] $$$$ 2024타경12345")
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
    assert "$$$$ 2024타경12345" in text.splitlines()[0]
    # 제목은 헤더가 아니라 본문의 "제목:" 줄에 나온다.
    assert "제목: 강남 아파트 특급매물" in text


def test_representative_message_shows_only_known_fields():
    data = CaseMessageData(
        case_number="2024타경12345",
        rating="$$$$",
        title="제목",
        interest=InterestStats(court_views=10, madangs_views=5, blog_mentions=2, recent_blog_mentions=1),
    )
    text = build_representative_message(data)
    for field in [
        "사건번호:",
        "상태:",
        "관심도:",
        "법원경매 조회수:",
        "경매마당 조회수:",
        "블로그 언급:",
        "최근 7일 신규 블로그:",
        "첨부 이미지:",
    ]:
        assert field in text
    # 값이 없는 항목(법원/소재지/감정가/최저가/매각기일/물건번호/링크)은 아예 숨긴다.
    for hidden_field in ["법원:", "소재지:", "감정가:", "최저가:", "매각기일:", "물건번호:", "링크:"]:
        assert hidden_field not in text


def test_representative_message_shows_present_fields_and_html_links():
    data = CaseMessageData(
        case_number="2024타경12345",
        rating="$$$$",
        title="제목",
        auction=AuctionFields(
            court="서울중앙지방법원",
            address="서울시 강남구",
            appraisal_price=500_000_000,
            madangs_link="https://www.madangs.com/search?keyword=2024타경12345",
            court_link="https://www.courtauction.go.kr/pgj/index.on",
        ),
    )
    text = build_representative_message(data)
    assert "법원: 서울중앙지방법원" in text
    assert "소재지: 서울시 강남구" in text
    assert "감정가: 500,000,000원" in text
    assert "링크:" in text
    assert '<a href="https://www.madangs.com/search?keyword=2024타경12345">경매마당</a>' in text
    assert '<a href="https://www.courtauction.go.kr/pgj/index.on">법원경매</a>' in text
    # 긴 URL이 그대로 노출되면 안 된다.
    assert "https://www.madangs.com" not in text.split("링크:")[0]


def test_representative_message_header_low_grade_uses_brackets():
    data = CaseMessageData(case_number="2024타경1", rating="낮은등급", title="제목")
    text = build_representative_message(data)
    assert text.startswith("[입찰일 확인중] [낮은등급] 2024타경1")


def test_representative_message_header_grade_unknown_uses_brackets():
    data = CaseMessageData(case_number="2024타경1", rating="등급확인", title="제목")
    text = build_representative_message(data)
    assert text.startswith("[입찰일 확인중] [등급확인] 2024타경1")


def test_representative_message_header_dollar_rating_not_bracketed():
    data = CaseMessageData(case_number="2024타경1", rating="$$$", title="사당 15 추천 $$$")
    text = build_representative_message(data)
    assert text.startswith("[입찰일 확인중] $$$ 2024타경1")
    assert "[$$$]" not in text


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
