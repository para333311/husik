"""페이지를 사건번호 위치 기준으로 나눠 사건별 crop 이미지를 만든다.

한 페이지 안에 사건번호가 여러 개 있을 때 페이지 전체 이미지를 사건 하나에
붙이면 다른 사건의 이미지가 섞여 들어간다. 이를 막기 위해 사건번호가 등장하는
줄의 y좌표를 기준으로 페이지를 세로로 나눠, 사건별로 그 구간만 crop한다.

레이아웃(줄 bbox)은 다음 순서로 확보한다:
1. PDF 텍스트 레이어가 있으면 render.py가 이미 계산해둔 native_lines 사용.
2. 없으면(이미지 PDF) tesseract의 image_to_data로 OCR bbox를 뽑는다.
3. 그래도 못 구하면 whole-page fallback으로 처리하되, 한 페이지에 사건번호가
   2개 이상이면 확신할 수 없으므로 "검토필요"로 분리해 보낸다 (절대 섞지 않음).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from husik.pdf.render import NativeLine, RenderedPage
from husik.utils.text import extract_case_numbers, looks_like_uncertain_case_marker

logger = logging.getLogger(__name__)

REVIEW_LABEL = "검토필요"


@dataclass
class CaseMarker:
    case_number: str
    y_top: float


@dataclass
class PageLayout:
    image_height: int
    markers: list[CaseMarker] = field(default_factory=list)
    uncertain_marker_found: bool = False


def _layout_from_lines(lines: list[NativeLine], image_height: int) -> PageLayout:
    markers: list[CaseMarker] = []
    uncertain = False
    for line in lines:
        found = extract_case_numbers(line.text)
        if found:
            markers.append(CaseMarker(case_number=found[0], y_top=line.y_top))
        elif looks_like_uncertain_case_marker(line.text):
            uncertain = True
    return PageLayout(image_height=image_height, markers=markers, uncertain_marker_found=uncertain)


def _tesseract_layout(image_path: Path) -> PageLayout | None:
    try:
        import pytesseract
        from pytesseract import Output
    except ImportError:
        return None

    try:
        with Image.open(image_path) as img:
            height = img.height
            data = pytesseract.image_to_data(img, lang="kor+eng", output_type=Output.DICT)
    except Exception as exc:  # pragma: no cover - depends on system tesseract install
        logger.warning("tesseract layout detection failed for %s: %s", image_path.name, exc)
        return None

    lines: dict[tuple[int, int, int], dict] = {}
    count = len(data.get("text", []))
    for i in range(count):
        word = (data["text"][i] or "").strip()
        if not word:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        top = data["top"][i]
        bottom = top + data["height"][i]
        entry = lines.setdefault(key, {"words": [], "y_top": top, "y_bottom": bottom})
        entry["words"].append(word)
        entry["y_top"] = min(entry["y_top"], top)
        entry["y_bottom"] = max(entry["y_bottom"], bottom)

    native_lines = [
        NativeLine(text=" ".join(v["words"]), y_top=v["y_top"], y_bottom=v["y_bottom"])
        for v in sorted(lines.values(), key=lambda v: v["y_top"])
    ]
    return _layout_from_lines(native_lines, image_height=height)


def detect_page_layout(rendered: RenderedPage) -> PageLayout | None:
    """레이아웃(사건번호별 y좌표)을 확보한다. 완전히 실패하면 None을 반환한다."""
    if rendered.native_lines:
        return _layout_from_lines(rendered.native_lines, image_height=rendered.image_height)
    return _tesseract_layout(rendered.image_path)


def crop_band(image_path: Path, y_top: float, y_bottom: float, out_path: Path) -> Path:
    with Image.open(image_path) as img:
        width, height = img.size
        top = max(0, min(int(y_top), height - 1))
        bottom = max(top + 1, min(int(y_bottom), height))
        cropped = img.crop((0, top, width, bottom))
        cropped.save(out_path, "JPEG", quality=90, optimize=True)
    return out_path


@dataclass
class ImageSegment:
    case_number: str  # REVIEW_LABEL일 수 있음
    page_no: int
    image_path: Path
    is_review: bool = False
    from_mixed_page: bool = False  # 이 페이지에 사건번호가 2개 이상 있었는지


def segment_page(
    rendered: RenderedPage,
    fallback_case_numbers: list[str],
    work_dir: Path,
) -> list[ImageSegment]:
    """페이지 하나를 사건번호 기준 구간으로 나눠 crop 이미지 목록을 만든다.

    - 사건번호가 없으면 빈 리스트를 반환한다 (continuation 여부는 호출자가 판단).
    - 사건번호가 1개면 페이지 전체를 그 사건에 배정한다 (crop 불필요).
    - 사건번호가 2개 이상이고 bbox를 구했으면 각 사건번호 줄 y좌표로 나눠 crop한다.
    - 사건번호가 2개 이상인데 bbox를 못 구했으면(확신 없음) "검토필요"로 페이지 전체를 보낸다.
    """
    if not fallback_case_numbers:
        return []

    layout = detect_page_layout(rendered)

    if layout is None or len(layout.markers) <= 1:
        if len(fallback_case_numbers) == 1:
            return [
                ImageSegment(
                    case_number=fallback_case_numbers[0],
                    page_no=rendered.page_no,
                    image_path=rendered.image_path,
                )
            ]
        # bbox 없이 사건번호 2개 이상 감지 -> 확신 없음, 섞이는 것보다 검토필요로 분리
        logger.warning(
            "page %s has %d case numbers but no layout bbox; routing to review",
            rendered.page_no,
            len(fallback_case_numbers),
        )
        return [
            ImageSegment(
                case_number=REVIEW_LABEL,
                page_no=rendered.page_no,
                image_path=rendered.image_path,
                is_review=True,
                from_mixed_page=True,
            )
        ]

    markers = layout.markers
    mixed = len(markers) > 1
    segments: list[ImageSegment] = []
    for i, marker in enumerate(markers):
        y_top = marker.y_top
        y_bottom = markers[i + 1].y_top if i + 1 < len(markers) else layout.image_height
        if y_bottom <= y_top:
            continue
        crop_path = work_dir / f"page_{rendered.page_no:03d}_crop{i + 1:02d}.jpg"
        crop_band(rendered.image_path, y_top, y_bottom, crop_path)
        segments.append(
            ImageSegment(
                case_number=marker.case_number,
                page_no=rendered.page_no,
                image_path=crop_path,
                from_mixed_page=mixed,
            )
        )
    return segments
