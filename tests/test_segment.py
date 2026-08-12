from pathlib import Path

import pytest
from PIL import Image

from husik.pdf.render import NativeLine, RenderedPage
from husik.pdf.segment import (
    REVIEW_LABEL,
    ImageSegment,
    compose_slides_into_bundles,
    detect_page_layout,
    segment_page,
)


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


def test_detect_page_layout_ignores_right_side_body_case_numbers():
    rendered = _rendered(
        1,
        [
            NativeLine(text="2025타경1708", y_top=20, y_bottom=40, x_left=20, x_right=180),
            NativeLine(text="본문 참조 2016타경7487", y_top=200, y_bottom=220, x_left=500, x_right=760),
        ],
    )

    layout = detect_page_layout(rendered)
    assert layout is not None
    assert [m.case_number for m in layout.markers] == ["2025타경1708"]


def test_review_segment_never_shares_case_number_with_real_case(tmp_path):
    rendered = _rendered(1, [])
    segments = segment_page(rendered, ["2025타경1001", "2025타경1002", "2025타경1003"], tmp_path)
    assert all(seg.case_number == REVIEW_LABEL for seg in segments)


def _slide(
    tmp_path,
    idx: int,
    page_no: int,
    order_index: int,
    case_number: str = "2025타경1708",
) -> ImageSegment:
    path = tmp_path / f"slide_{idx:02d}.jpg"
    Image.new("RGB", (400, 240 + idx * 10), color="white").save(path)
    return ImageSegment(
        case_number=case_number,
        page_no=page_no,
        order_index=order_index,
        image_path=path,
        source_refs=[f"p{page_no} crop{order_index}"],
    )


def test_compose_bundle_counts_follow_4_slide_rule(tmp_path):
    one = [_slide(tmp_path, 1, 1, 1)]
    assert len(compose_slides_into_bundles("2025타경1708", one, tmp_path)) == 1

    four = [_slide(tmp_path, i, i, 1) for i in range(1, 5)]
    assert len(compose_slides_into_bundles("2025타경1708", four, tmp_path)) == 1

    five = [_slide(tmp_path, i, i, 1) for i in range(1, 6)]
    assert len(compose_slides_into_bundles("2025타경1708", five, tmp_path)) == 2

    six = [_slide(tmp_path, i, i, 1) for i in range(1, 7)]
    six_bundles = compose_slides_into_bundles("2025타경1708", six, tmp_path)
    assert len(six_bundles) == 2
    assert six_bundles[0].slide_indices == [1, 2, 3, 4]
    assert six_bundles[1].slide_indices == [5, 6]

    nine = [_slide(tmp_path, i, i, 1) for i in range(1, 10)]
    assert len(compose_slides_into_bundles("2025타경1708", nine, tmp_path)) == 3


def test_compose_bundle_keeps_slide_order(tmp_path):
    slides = [
        _slide(tmp_path, 1, 2, 2),
        _slide(tmp_path, 2, 1, 1),
        _slide(tmp_path, 3, 2, 1),
        _slide(tmp_path, 4, 1, 2),
        _slide(tmp_path, 5, 3, 1),
    ]
    bundles = compose_slides_into_bundles("2025타경1708", slides, tmp_path)

    assert [b.slide_indices for b in bundles] == [[1, 2, 3, 4], [5]]
    assert bundles[0].source_refs == ["p1 crop1", "p1 crop2", "p2 crop1", "p2 crop2"]
    assert bundles[1].source_refs == ["p3 crop1"]


def test_compose_bundle_rejects_mixed_case_numbers(tmp_path):
    slides = [
        _slide(tmp_path, 1, 1, 1, case_number="2025타경1708"),
        _slide(tmp_path, 2, 1, 2, case_number="2025타경9999"),
    ]

    with pytest.raises(ValueError, match="mixed case numbers"):
        compose_slides_into_bundles("2025타경1708", slides, tmp_path)


def test_bundle_image_is_single_vertical_column(tmp_path):
    slides = [_slide(tmp_path, i, i, 1) for i in range(1, 5)]
    bundles = compose_slides_into_bundles("2025타경1708", slides, tmp_path)

    assert len(bundles) == 1
    with Image.open(bundles[0].image_path) as out_img:
        assert out_img.width == 1800
        assert out_img.height > out_img.width
