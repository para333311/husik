"""실제 PDF를 렌더링해 사건 단위 이미지 분리가 실제로 동작하는지 확인하는 통합 테스트."""
from husik.config import Config
from husik.state.store import StateStore
from husik.telegram.ingest import process_pdf

fitz = __import__("fitz")


def _build_mixed_page_pdf(path) -> None:
    doc = fitz.open()
    font = fitz.Font("korea")
    page = doc.new_page()
    page.insert_font(fontname="F0", fontbuffer=font.buffer)
    page.insert_text((50, 80), "사당 15 추천 $$$", fontsize=14, fontname="F0")
    page.insert_text((50, 105), "2025타경102095", fontsize=14, fontname="F0")
    page.insert_text((50, 130), "매각기일 : 2026.05.19", fontsize=13, fontname="F0")
    page.insert_text((50, 500), "둔촌 34 매물", fontsize=14, fontname="F0")
    page.insert_text((50, 525), "2025타경200000", fontsize=14, fontname="F0")
    doc.save(str(path))
    doc.close()


def _build_multi_case_pdf(path) -> None:
    doc = fitz.open()
    font = fitz.Font("korea")

    def add_page(lines):
        p = doc.new_page()
        p.insert_font(fontname="F0", fontbuffer=font.buffer)
        for i, line in enumerate(lines):
            p.insert_text((50, 72 + i * 20), line, fontsize=14, fontname="F0")

    add_page(["강남 아파트 특급매물", "2024타경12345", "$$$$"])
    add_page(["소재지: 서울시 강남구"])
    add_page(["부산 상가 매물", "2024타경9999"])

    doc.save(str(path))
    doc.close()


def _make_config(tmp_path) -> Config:
    return Config(
        telegram_auction_bot_token="",
        telegram_audio_bot_token="",
        telegram_auction_channel_id="-1001234567890",
        telegram_audio_channel_id="",
        telegram_allowed_user_id="",
        openai_api_key="",
        notion_token="",
        notion_auction_db_url="",
        naver_client_id="",
        naver_client_secret="",
        court_auction_enabled=False,
        madangs_enabled=False,
        blog_monitor_enabled=False,
        state_dir=tmp_path / "state",
        tmp_dir=tmp_path / "tmp",
    )


def test_two_case_numbers_on_one_page_produce_non_overlapping_images(tmp_path):
    pdf_path = tmp_path / "mixed_page.pdf"
    _build_mixed_page_pdf(pdf_path)
    config = _make_config(tmp_path)
    state = StateStore(config.state_dir)

    report = process_pdf(pdf_path, config, state, send=False, tmp_root=config.tmp_dir)

    case_numbers = {r.case_number for r in report.results}
    assert case_numbers == {"2025타경102095", "2025타경200000"}
    for r in report.results:
        assert r.mixed_page is True
        assert r.processed is True


def test_case_number_without_rating_is_still_processed_and_gets_its_own_images(tmp_path):
    pdf_path = tmp_path / "multi_case.pdf"
    _build_multi_case_pdf(pdf_path)
    config = _make_config(tmp_path)
    state = StateStore(config.state_dir)

    report = process_pdf(pdf_path, config, state, send=False, tmp_root=config.tmp_dir)

    by_case = {r.case_number: r for r in report.results}
    assert by_case["2024타경12345"].rating == "$$$$"
    assert by_case["2024타경12345"].processed is True
    assert by_case["2024타경12345"].image_count == 1
    # 등급이 전혀 안 잡혀도(등급확인) 여전히 전송 대상이어야 한다.
    assert by_case["2024타경9999"].rating == "등급확인"
    assert by_case["2024타경9999"].processed is True
    # 사건마다 자기 페이지의 이미지만 매핑돼야 한다 (다른 사건과 안 섞임).
    assert "p1" in by_case["2024타경12345"].page_image_map
    assert "p3" in by_case["2024타경9999"].page_image_map
    assert "p3" not in by_case["2024타경12345"].page_image_map


def test_single_case_multiple_pages_are_merged_into_one_image(tmp_path):
    pdf_path = tmp_path / "single_case_multi_page.pdf"
    doc = fitz.open()
    font = fitz.Font("korea")

    page1 = doc.new_page()
    page1.insert_font(fontname="F0", fontbuffer=font.buffer)
    page1.insert_text((50, 80), "상계3 $$+", fontsize=14, fontname="F0")
    page1.insert_text((50, 105), "2025타경13320", fontsize=14, fontname="F0")

    page2 = doc.new_page()
    page2.insert_font(fontname="F0", fontbuffer=font.buffer)
    page2.insert_text((50, 80), "추가 설명 페이지", fontsize=14, fontname="F0")

    doc.save(str(pdf_path))
    doc.close()

    config = _make_config(tmp_path)
    state = StateStore(config.state_dir)

    report = process_pdf(pdf_path, config, state, send=False, tmp_root=config.tmp_dir)

    assert len(report.results) == 1
    result = report.results[0]
    assert result.case_number == "2025타경13320"
    assert result.page_start == 1 and result.page_end == 2
    assert result.image_count == 1
    assert result.processing_mode == "page/full"


def test_sale_date_is_extracted_into_case_record(tmp_path):
    pdf_path = tmp_path / "mixed_page.pdf"
    _build_mixed_page_pdf(pdf_path)
    config = _make_config(tmp_path)
    state = StateStore(config.state_dir)

    report = process_pdf(pdf_path, config, state, send=False, tmp_root=config.tmp_dir)

    by_case = {r.case_number: r for r in report.results}
    sale_date = by_case["2025타경102095"].sale_date
    assert sale_date is not None
    assert f"{sale_date.year}.{sale_date.month}.{sale_date.day}" == "2026.5.19"
