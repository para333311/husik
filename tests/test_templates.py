from datetime import date

from husik.telegram.templates import (
    AuctionFields,
    CaseMessageData,
    build_award_update,
    build_event_update,
    build_representative_message,
)


def test_representative_message_simple_format():
    data = CaseMessageData(
        case_number="2025타경1708",
        rating="$$$",
        title="효창공원 시프트 SSS",
        auction=AuctionFields(sale_date=date(2026, 5, 19), status="낙찰"),
        image_count=3,
    )

    text = build_representative_message(data)

    assert text == "\n".join(
        [
            "[2025타경1708]",
            "효창공원 시프트 SSS",
            "· 매각기일 2026.5.19",
            "· 낙찰",
        ]
    )


def test_representative_message_hides_sale_date_when_missing():
    data = CaseMessageData(
        case_number="2025타경1708",
        rating="$$$",
        title="효창공원 시프트 SSS",
        image_count=1,
    )
    text = build_representative_message(data)

    assert "매각기일" not in text


def test_representative_message_hides_status_when_unknown():
    data = CaseMessageData(
        case_number="2025타경1708",
        rating="$$$",
        title="효창공원 시프트 SSS",
        auction=AuctionFields(status="확인중"),
    )
    text = build_representative_message(data)

    assert "·" not in text
    assert "상태" not in text


def test_representative_message_hides_interest_link_blog_notion_texts():
    data = CaseMessageData(
        case_number="2025타경1708",
        rating="$$$",
        title="효창공원 시프트 SSS",
        image_count=3,
    )

    text = build_representative_message(data)

    forbidden = [
        "관심도",
        "법원경매 조회수",
        "경매마당 조회수",
        "블로그 언급",
        "최근 7일 신규 블로그",
        "경매마당 링크",
        "법원경매 링크",
        "휴식형 강의내용",
        "블로그 분석글",
        "누적기록",
        "Notion 상세페이지 참고",
        "아래 첨부 이미지",
        "링크:",
        "업데이트:",
        "이미지",
        "상태 :",
        "ㅇ ",
    ]
    for word in forbidden:
        assert word not in text


def test_representative_message_omits_title_when_missing():
    data = CaseMessageData(case_number="2025타경1708", rating="$$$", title="2025타경1708", image_count=2)

    text = build_representative_message(data)

    assert text.splitlines()[0] == "[2025타경1708]"
    assert len(text.splitlines()) == 1


def test_event_update_preserves_event_prefix_and_existing_message():
    data = CaseMessageData(
        case_number="2025타경1708",
        rating="$$$",
        title="효창공원 시프트 SSS",
        image_count=1,
    )
    updated = build_event_update("블로그업데이트", data, existing_message="기존 대표 메시지")

    assert updated.startswith("[블로그업데이트] [2025타경1708]")
    assert "기존 대표 메시지" in updated


def test_award_update_uses_same_minimal_body():
    data = CaseMessageData(
        case_number="2025타경1708",
        rating="$$$",
        title="효창공원 시프트 SSS",
        sale_date_text="2026.5.19",
        status_text="유찰",
    )
    updated = build_award_update(data, existing_message="이전 내용")

    assert "· 매각기일 2026.5.19" in updated
    assert "· 유찰" in updated
    assert "상태 :" not in updated
    assert "이미지" not in updated
