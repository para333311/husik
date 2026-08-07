"""페이지 내 사건표 시작점을 기준으로 필요한 경우에만 크게 세로 분할한다.

정책:
- 기본은 페이지 전체를 한 사건 이미지로 사용한다.
- 한 페이지에 좌측 영역 사건번호 시작점이 2개 이상일 때만 표 단위 세로 분할한다.
- 세부 요소(사진/지도/제목) 단위의 미세 crop은 하지 않는다.
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
LEFT_MARKER_X_RATIO = 0.45
MAX_MARKER_LINE_LENGTH = 40


@dataclass
class CaseMarker:
    case_number: str
    y_top: float
    x_left: float


@dataclass
class PageLayout:
    image_width: int
    image_height: int
    markers: list[CaseMarker] = field(default_factory=list)
    uncertain_marker_found: bool = False


def _looks_like_table_start_line(text: str) -> bool:
    # 본문 문장 속 과거 사건번호 오탐을 줄이기 위해 너무 긴 라인은 제외한다.
    return len((text or "").strip()) <= MAX_MARKER_LINE_LENGTH


def _layout_from_lines(lines: list[NativeLine], image_width: int, image_height: int) -> PageLayout:
    markers: list[CaseMarker] = []
    uncertain = False
    marker_keys: set[tuple[str, int]] = set()

    for line in lines:
        if line.x_left > image_width * LEFT_MARKER_X_RATIO:
            continue

        found = extract_case_numbers(line.text)
        if found and _looks_like_table_start_line(line.text):
            key = (found[0], int(line.y_top))
            if key in marker_keys:
                continue
            marker_keys.add(key)
            markers.append(CaseMarker(case_number=found[0], y_top=line.y_top, x_left=line.x_left))
        elif looks_like_uncertain_case_marker(line.text):
            uncertain = True

    markers.sort(key=lambda m: m.y_top)
    return PageLayout(
        image_width=image_width,
        image_height=image_height,
        markers=markers,
        uncertain_marker_found=uncertain,
    )


def _tesseract_layout(image_path: Path) -> PageLayout | None:
    try:
        import pytesseract
        from pytesseract import Output
    except ImportError:
        return None

    try:
        with Image.open(image_path) as img:
            width, height = img.size
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
        left = data["left"][i]
        top = data["top"][i]
        right = left + data["width"][i]
        bottom = top + data["height"][i]
        entry = lines.setdefault(
            key,
            {"words": [], "x_left": left, "x_right": right, "y_top": top, "y_bottom": bottom},
        )
        entry["words"].append(word)
        entry["x_left"] = min(entry["x_left"], left)
        entry["x_right"] = max(entry["x_right"], right)
        entry["y_top"] = min(entry["y_top"], top)
        entry["y_bottom"] = max(entry["y_bottom"], bottom)

    native_lines = [
        NativeLine(
            text=" ".join(v["words"]),
            y_top=v["y_top"],
            y_bottom=v["y_bottom"],
            x_left=v["x_left"],
            x_right=v["x_right"],
        )
        for v in sorted(lines.values(), key=lambda v: v["y_top"])
    ]
    return _layout_from_lines(native_lines, image_width=width, image_height=height)


def detect_page_layout(rendered: RenderedPage) -> PageLayout | None:
    """레이아웃(사건번호별 y좌표)을 확보한다. 완전히 실패하면 None을 반환한다."""
    if rendered.native_lines:
        return _layout_from_lines(
            rendered.native_lines,
            image_width=rendered.image_width,
            image_height=rendered.image_height,
        )
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
    """한 페이지를 사건표 시작 y 기준으로 크게 분할한다.

    - 사건번호가 없으면 빈 리스트.
    - 사건번호 1개면 페이지 전체 이미지 사용.
    - 사건번호 2개 이상 + bbox 성공 시에만 표 단위 세로 분할.
    - bbox 실패 시 REVIEW로 분리(다른 사건에 섞지 않음).
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

        logger.warning(
            "page %s has %d candidate case starts but no usable layout; routing to review",
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
    if len(markers) == 1:
        return [
            ImageSegment(
                case_number=markers[0].case_number,
                page_no=rendered.page_no,
                image_path=rendered.image_path,
            )
        ]

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
                from_mixed_page=True,
            )
        )
    return segments
