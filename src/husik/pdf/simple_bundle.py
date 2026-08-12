"""PDF를 페이지 순서대로 4장씩 세로 합성하는 단순 번들 경로."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from husik.pdf.render import RenderedPage, render_pdf_to_images

PAGES_PER_COMPOSITE = 4
DEFAULT_COMPOSITE_WIDTH = 1600
DEFAULT_PAGE_GAP = 30
DEFAULT_JPEG_QUALITY = 88
MAX_TELEGRAM_PHOTO_BYTES = 9 * 1024 * 1024


@dataclass
class CompositeImage:
    start_page: int
    end_page: int
    source_page_numbers: list[int]
    image_path: Path


def render_pdf_pages(pdf_path: Path, work_dir: Path) -> list[RenderedPage]:
    pages_dir = work_dir / "pages"
    return render_pdf_to_images(pdf_path, pages_dir)


def _fit_to_width(img: Image.Image, target_width: int) -> Image.Image:
    if img.width == target_width:
        return img.copy()
    ratio = target_width / max(1, img.width)
    height = max(1, int(img.height * ratio))
    return img.resize((target_width, height), Image.LANCZOS)


def _save_composite_with_fallback(
    base_image: Image.Image,
    out_path: Path,
    width: int,
    quality: int,
) -> Path:
    current_width = width
    current_quality = quality

    while True:
        if base_image.width != current_width:
            candidate = _fit_to_width(base_image, current_width)
        else:
            candidate = base_image
        candidate.save(out_path, "JPEG", quality=current_quality, optimize=True)
        if out_path.stat().st_size <= MAX_TELEGRAM_PHOTO_BYTES:
            return out_path

        if current_width <= 1100 and current_quality <= 72:
            return out_path

        if current_width > 1100:
            current_width = max(1100, int(current_width * 0.9))
        if current_quality > 72:
            current_quality = max(72, current_quality - 5)


def compose_pages_by_four(
    rendered_pages: list[RenderedPage],
    out_dir: Path,
    *,
    composite_width: int = DEFAULT_COMPOSITE_WIDTH,
    page_gap: int = DEFAULT_PAGE_GAP,
    jpeg_quality: int = DEFAULT_JPEG_QUALITY,
) -> list[CompositeImage]:
    out_dir.mkdir(parents=True, exist_ok=True)
    bundles: list[CompositeImage] = []

    ordered = sorted(rendered_pages, key=lambda p: p.page_no)
    for start in range(0, len(ordered), PAGES_PER_COMPOSITE):
        group = ordered[start : start + PAGES_PER_COMPOSITE]
        if len(group) > PAGES_PER_COMPOSITE:
            raise ValueError("composite source pages must be <= 4")

        source_pages = [p.page_no for p in group]
        images: list[Image.Image] = []
        try:
            for page in group:
                with Image.open(page.image_path) as src:
                    resized = _fit_to_width(src.convert("RGB"), composite_width)
                    images.append(resized)

            total_height = sum(img.height for img in images) + page_gap * (len(images) - 1)
            canvas = Image.new("RGB", (composite_width, total_height), color="white")
            y = 0
            for img in images:
                canvas.paste(img, (0, y))
                y += img.height + page_gap

            start_page = source_pages[0]
            end_page = source_pages[-1]
            out_path = out_dir / f"image_{start_page:03d}_{end_page:03d}.jpg"
            _save_composite_with_fallback(canvas, out_path, composite_width, jpeg_quality)

            bundles.append(
                CompositeImage(
                    start_page=start_page,
                    end_page=end_page,
                    source_page_numbers=source_pages,
                    image_path=out_path,
                )
            )
        finally:
            for img in images:
                img.close()

    return bundles


def save_composite_images(
    pdf_path: Path,
    work_dir: Path,
    *,
    composite_width: int = DEFAULT_COMPOSITE_WIDTH,
    page_gap: int = DEFAULT_PAGE_GAP,
    jpeg_quality: int = DEFAULT_JPEG_QUALITY,
) -> list[CompositeImage]:
    rendered_pages = render_pdf_pages(pdf_path, work_dir)
    bundles_dir = work_dir / "bundles"
    return compose_pages_by_four(
        rendered_pages,
        bundles_dir,
        composite_width=composite_width,
        page_gap=page_gap,
        jpeg_quality=jpeg_quality,
    )
