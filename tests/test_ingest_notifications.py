from husik.telegram.ingest import (
    CHANNEL_FAIL_MSG,
    NO_CASE_MSG,
    NOTION_FAIL_MSG,
    OCR_FAIL_MSG,
    PdfRunResult,
    build_result_notifications,
)
from husik.telegram.templates import CaseMessageData, build_representative_message
from husik.utils.text import clean_title


def test_zero_detected_cases_produces_no_case_message():
    result = PdfRunResult(detected_cases=0)
    notes = build_result_notifications(result)
    assert notes == [NO_CASE_MSG]


def test_ocr_failed_takes_priority():
    result = PdfRunResult(ocr_failed=True)
    assert build_result_notifications(result) == [OCR_FAIL_MSG]


def test_channel_send_failed_message():
    result = PdfRunResult(detected_cases=1, channel_send_failed=True)
    assert build_result_notifications(result) == [CHANNEL_FAIL_MSG]


def test_success_message_includes_detected_and_sent_counts():
    result = PdfRunResult(detected_cases=1, cases_sent=1, images_sent=5, notion_upserted=1)
    notes = build_result_notifications(result)
    assert notes == ["처리 완료: 사건번호 1개 감지, 1건 전송, 5개 이미지 생성, 노션 1건 업데이트"]


def test_notion_failure_prepended_before_success_message():
    result = PdfRunResult(detected_cases=1, cases_sent=1, images_sent=3, any_notion_failed=True)
    notes = build_result_notifications(result)
    assert notes[0] == NOTION_FAIL_MSG
    assert notes[1].startswith("처리 완료:")


def test_partial_image_failure_appends_extra_note():
    result = PdfRunResult(detected_cases=1, cases_sent=1, images_sent=4, images_failed=2)
    notes = build_result_notifications(result)
    assert any("이미지 일부 전송 실패" in n and "2장" in n for n in notes)


def test_always_returns_at_least_one_notification():
    # 완전 무반응 상태를 방지: 어떤 조합이든 최소 1개는 반환해야 한다.
    assert len(build_result_notifications(PdfRunResult())) >= 1


def test_clean_title_removes_forbidden_terms_for_pdf_ingest_output():
    raw = "[2025타경12975] [투기과열지구/조정대상지역] 매수맛집 부동산강제경매 상도24 $$"
    assert clean_title(raw) == "2025타경12975 상도24 $$"


def test_representative_message_does_not_include_blog_or_link_lines():
    title = clean_title("상도24 $$ 투기과열지구 링크 블로그")
    message = build_representative_message(
        CaseMessageData(
            case_number="2025타경12975",
            rating="$$$",
            title=title,
            sale_date_text="2026.6.9",
            status_text="낙찰",
        )
    )

    assert message == "[2025타경12975]\n상도24 $$\n· 매각기일 2026.6.9\n· 낙찰"
