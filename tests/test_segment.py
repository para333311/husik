from pathlib import Path

from husik.pdf.render import NativeLine, RenderedPage
from husik.pdf.segment import REVIEW_LABEL, segment_page


def _rendered(page_no, native_lines, image_height=1000, image_path=None):
    return RenderedPage(
        page_no=page_no,
        image_path=image_path or Path(f"/tmp/page_{page_no}.jpg"),
        native_text="\n".join(line.text for line in native_lines),
        image_width=800,
        image_height=image_height,
        native_lines=native_lines,
    )


def test_single_case_number_uses_whole_page(tmp_path):
    rendered = _rendered(1, [NativeLine(text="2025타경102095", y_top=10, y_bottom=40)])
    segments = segment_page(rendered, ["2025타경102095"], tmp_path)
    assert len(segments) == 1
    assert segments[0].case_number == "2025타경102095"
    assert segments[0].image_path == rendered.image_path
    assert segments[0].is_review is False


def test_no_case_numbers_returns_empty(tmp_path):
    rendered = _rendered(1, [])
    assert segment_page(rendered, [], tmp_path) == []


def test_two_case_numbers_on_one_page_split_by_bbox(tmp_path, monkeypatch):
    from PIL import Image

    real_image_path = tmp_path / "page_001.jpg"
    Image.new("RGB", (400, 1000), color="white").save(real_image_path)

    rendered = _rendered(
        1,
        [
            NativeLine(text="2025타경102095", y_top=10, y_bottom=40),
            NativeLine(text="사당 15 추천 $$$", y_top=45, y_bottom=70),
            NativeLine(text="2025타경200000", y_top=500, y_bottom=530),
            NativeLine(text="둔촌 34 매물", y_top=535, y_bottom=560),
        ],
        image_height=1000,
        image_path=real_image_path,
    )

    segments = segment_page(rendered, ["2025타경102095", "2025타경200000"], tmp_path)

    assert len(segments) == 2
    case_numbers = {seg.case_number for seg in segments}
    assert case_numbers == {"2025타경102095", "2025타경200000"}
    # 서로 다른 crop 파일이어야 하고, 원본 페이지 이미지 그대로가 아니어야 한다.
    assert segments[0].image_path != segments[1].image_path
    assert segments[0].image_path != rendered.image_path
    assert all(seg.from_mixed_page for seg in segments)
    for seg in segments:
        assert seg.image_path.exists()


def test_two_case_numbers_without_bbox_routes_to_review(tmp_path):
    # native_lines가 비어 있고(텍스트 레이어 없음) tesseract도 없는 상황을 흉내낸다:
    # bbox를 구할 수 없는데 사건번호가 2개 이상이면 섞이지 않도록 검토필요로 보낸다.
    rendered = _rendered(1, [])  # bbox 정보 없음
    segments = segment_page(rendered, ["2025타경102095", "2025타경200000"], tmp_path)

    assert len(segments) == 1
    assert segments[0].is_review is True
    assert segments[0].case_number == REVIEW_LABEL
    assert segments[0].image_path == rendered.image_path


def test_review_segment_never_shares_case_number_with_real_case(tmp_path):
    rendered = _rendered(1, [])
    segments = segment_page(rendered, ["2025타경1001", "2025타경1002", "2025타경1003"], tmp_path)
    assert all(seg.case_number == REVIEW_LABEL for seg in segments)
