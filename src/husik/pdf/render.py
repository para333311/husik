"""PyMuPDF로 PDF 페이지를 텔레그램에서 바로 보기 좋은 JPG 이미지로 렌더링한다."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

DEFAULT_DPI = 200
MAX_DIMENSION = 2000
JPEG_QUALITY = 85


@dataclass
class RenderedPage:
    page_no: int
    image_path: Path
    native_text: str


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
            if max(image.size) > MAX_DIMENSION:
                ratio = MAX_DIMENSION / max(image.size)
                new_size = (max(1, int(image.width * ratio)), max(1, int(image.height * ratio)))
                image = image.resize(new_size, Image.LANCZOS)

            image_path = out_dir / f"page_{index + 1:03d}.jpg"
            image.save(image_path, "JPEG", quality=JPEG_QUALITY, optimize=True)
            pages.append(RenderedPage(page_no=index + 1, image_path=image_path, native_text=native_text))

    return pages
