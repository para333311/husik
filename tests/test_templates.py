from datetime import date

from husik.telegram.templates import (
    AuctionFields,
    CaseMessageData,
    build_award_update,
    build_event_update,
    build_representative_message,
    truncate_message,
)


def test_representative_message_simple_format():
    data = CaseMessageData(
        case_number="2025타경1708",
        rating="$$$",
        title="효창공원 시프트 SSS",
        auction=AuctionFields(sale_date=date(2026, 5, 19)),
        image_count=3,
    )

    text = build_representative_message(data)

    assert text == "\n".join(
        [
            "[2025타경1708]",
            "효창공원 시프트 SSS",
            "ㅇ 매각기일 : 2026.5.19",
            "ㅇ 상태 :",
            "ㅇ 이미지 3장",
        ]
    )


def test_representative_message_keeps_sale_date_line_empty_when_missing():
    data = CaseMessageData(
        case_number="2025타경1708",
        rating="$$$",
        title="효창공원 시프트 SSS",
        image_count=1,
    )

    text = build_representative_message(data)

    assert "ㅇ 매각기일 : " in text
    assert "ㅇ 매각기일 :\n" not in text


def test_representative_message_omits_title_when_missing():
    data = CaseMessageData(case_number="2025타경1708", rating="$$$", title="2025타경1708", image_count=2)

    text = build_representative_message(data)

    assert text.splitlines()[0] == "[2025타경1708]"
    assert len(text.splitlines()) == 4


def test_representative_message_removes_interest_links_notion_phrases():
    data = CaseMessageData(
        case_number="2025타경1708",
        rating="$$$",
        title="효창공원 시프트 SSS",
        image_count=3,
    )

    text = build_representative_message(data)

    banned = [
        "관심도",
        "법원경매 조회수",
        "경매마당 조회수",
        "블로그 언급",
        "최근 7일 신규 블로그",
        "경매마당",
        "법원경매",
        "Notion 상세페이지 참고",
        "이미지 안내: 아래 첨부 이미지",
    ]
    for token in banned:
        assert token not in text


def test_event_update_prepends_new_block_above_existing():
    data = CaseMessageData(case_number="2024타경12345", rating="$$$$", title="제목")
    updated = build_event_update("블로그업데이트", data, existing_message="옛날 대표 메시지")
    assert updated.startswith("[블로그업데이트] [2024타경12345]")
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
