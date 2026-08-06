"""PyMuPDF로 PDF 페이지를 텔레그램에서 바로 보기 좋은 JPG 이미지로 렌더링한다.

사건 단위 이미지 분리(segment.py)를 위해, 텍스트 레이어가 있는 PDF라면 줄 단위
bounding box(native_lines)도 함께 뽑아 저장된 이미지와 같은 픽셀 좌표계로 변환해둔다.
이미지 PDF(텍스트 레이어 없음)라면 native_lines는 빈 리스트가 되고, 세그먼트 탐지는
OCR(tesseract) bbox로 fallback한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

DEFAULT_DPI = 200
MAX_DIMENSION = 2000
JPEG_QUALITY = 85


@dataclass
class NativeLine:
    text: str
    y_top: float
    y_bottom: float


@dataclass
class RenderedPage:
    page_no: int
    image_path: Path
    native_text: str
    image_width: int = 0
    image_height: int = 0
    native_lines: list[NativeLine] = field(default_factory=list)


def _build_native_lines(page: fitz.Page, matrix: fitz.Matrix, post_scale: float) -> list[NativeLine]:
    words = page.get_text("words")
    if not words:
        return []

    lines: dict[tuple[int, int], dict] = {}
    for x0, y0, x1, y1, word, block_no, line_no, _word_no in words:
        top_left = fitz.Point(x0, y0) * matrix
        bottom_right = fitz.Point(x1, y1) * matrix
        y_top = min(top_left.y, bottom_right.y) * post_scale
        y_bottom = max(top_left.y, bottom_right.y) * post_scale

        key = (block_no, line_no)
        entry = lines.setdefault(key, {"words": [], "y_top": y_top, "y_bottom": y_bottom})
        entry["words"].append(word)
        entry["y_top"] = min(entry["y_top"], y_top)
        entry["y_bottom"] = max(entry["y_bottom"], y_bottom)

    return [
        NativeLine(text=" ".join(v["words"]), y_top=v["y_top"], y_bottom=v["y_bottom"])
        for v in sorted(lines.values(), key=lambda v: v["y_top"])
    ]


def render_pdf_to_images(pdf_path: Path, out_dir: Path, dpi: int = DEFAULT_DPI) -> list[RenderedPage]:
    """PDF의 각 페이지를 out_dir 아래 page_NNN.jpg로 렌더링하고 native 텍스트를 함께 반환한다."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pages: list[RenderedPage] = []
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)

    with fitz.open(pdf_path) as doc:
        for index in range(len(doc)):
            page = doc.load_page(index)
            native_text = page.get_text("text") or ""
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

            post_scale = 1.0
            if max(image.size) > MAX_DIMENSION:
                ratio = MAX_DIMENSION / max(image.size)
                new_size = (max(1, int(image.width * ratio)), max(1, int(image.height * ratio)))
                image = image.resize(new_size, Image.LANCZOS)
                post_scale = ratio

            native_lines = _build_native_lines(page, matrix, post_scale)

            image_path = out_dir / f"page_{index + 1:03d}.jpg"
            image.save(image_path, "JPEG", quality=JPEG_QUALITY, optimize=True)
            pages.append(
                RenderedPage(
                    page_no=index + 1,
                    image_path=image_path,
                    native_text=native_text,
                    image_width=image.width,
                    image_height=image.height,
                    native_lines=native_lines,
                )
            )

    return pages
