from pathlib import Path

from husik.pdf.simple_bundle import PAGES_PER_COMPOSITE, save_composite_images

fitz = __import__("fitz")


def _build_pdf(path: Path, page_count: int) -> None:
    doc = fitz.open()
    font = fitz.Font("korea")
    for page_no in range(1, page_count + 1):
        page = doc.new_page(width=595, height=842)
        page.insert_font(fontname="F0", fontbuffer=font.buffer)
        page.insert_text((50, 100), f"PAGE {page_no}", fontsize=24, fontname="F0")
    doc.save(str(path))
    doc.close()


def test_composite_counts_follow_four_page_rule(tmp_path):
    expectations = {1: 1, 4: 1, 5: 2, 8: 2, 9: 3, 21: 6}

    for pages, expected_count in expectations.items():
        pdf_path = tmp_path / f"sample_{pages}.pdf"
        work_dir = tmp_path / f"work_{pages}"
        _build_pdf(pdf_path, pages)

        composites = save_composite_images(pdf_path, work_dir)

        assert len(composites) == expected_count
        assert composites[0].start_page == 1
        assert composites[0].source_page_numbers[0] == 1
        assert all(len(c.source_page_numbers) <= PAGES_PER_COMPOSITE for c in composites)


def test_filename_and_split_order_are_sequential(tmp_path):
    pdf_path = tmp_path / "sample_9.pdf"
    _build_pdf(pdf_path, 9)

    composites = save_composite_images(pdf_path, tmp_path / "work_9")

    names = [c.image_path.name for c in composites]
    assert names == ["image_001_004.jpg", "image_005_008.jpg", "image_009_009.jpg"]
    assert composites[0].source_page_numbers == [1, 2, 3, 4]
    assert composites[1].source_page_numbers == [5, 6, 7, 8]
    assert composites[2].source_page_numbers == [9]
