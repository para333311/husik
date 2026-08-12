from pathlib import Path

from PIL import Image

import husik.pdf.detect_cases as detect_module
from husik.pdf.detect_cases import analyze_page
from husik.pdf.render import RenderedPage
from husik.vision.base import CaseBlock, PageVisionResult, VisionCache, VisionProvider
from husik.vision.gemini import GeminiVisionProvider, _parse_case_blocks, _strip_code_fence


class StubVisionProvider(VisionProvider):
    provider_name = "stub"

    def __init__(self, result: PageVisionResult | None):
        self.result = result
        self.calls = 0

    @property
    def enabled(self) -> bool:
        return True

    @property
    def model_name(self) -> str:
        return "stub-v1"

    def analyze_page(self, image_path: Path, page_no: int, work_dir: Path) -> PageVisionResult | None:
        self.calls += 1
        return self.result


def _rendered(tmp_path: Path, page_no: int = 1, text: str = "") -> RenderedPage:
    image_path = tmp_path / f"page_{page_no:03d}.jpg"
    Image.new("RGB", (800, 1200), "white").save(image_path)
    return RenderedPage(
        page_no=page_no,
        image_path=image_path,
        native_text=text,
        image_width=800,
        image_height=1200,
    )


def test_strip_code_fence_json():
    raw = "```json\n{\"review_required\": false}\n```"
    assert _strip_code_fence(raw) == '{"review_required": false}'


def test_parse_case_blocks_normalizes_spaced_case_numbers():
    payload = """
    {
      "case_blocks": [
        {"case_number": "2025 타경 1708", "confidence": 0.95, "y_top": 0.1, "y_bottom": 0.9}
      ],
      "review_required": false
    }
    """
    result = _parse_case_blocks(payload)

    assert len(result.case_blocks) == 1
    assert result.case_blocks[0].case_number == "2025타경1708"


def test_gemini_provider_disabled_without_api_key(tmp_path):
    provider = GeminiVisionProvider(api_key="")
    assert provider.enabled is False
    image = tmp_path / "x.jpg"
    Image.new("RGB", (10, 10), "white").save(image)
    assert provider.analyze_page(image, 1, tmp_path) is None


def test_gemini_provider_failure_does_not_crash(tmp_path, monkeypatch):
    provider = GeminiVisionProvider(api_key="dummy", max_retries=1)
    image = tmp_path / "x.jpg"
    Image.new("RGB", (10, 10), "white").save(image)

    class DummyResp:
        def raise_for_status(self):
            raise RuntimeError("quota")

    monkeypatch.setattr("husik.vision.gemini.requests.post", lambda *a, **k: DummyResp())

    assert provider.analyze_page(image, 1, tmp_path) is None


def test_vision_cache_key_changes_when_schema_version_changes():
    key_v1 = VisionCache.build_key(
        pdf_hash="h",
        page_no=1,
        image_hash="img",
        provider_name="gemini",
        model_name="gemini-2.5-flash",
        schema_version="case-boundary-v1",
    )
    key_v2 = VisionCache.build_key(
        pdf_hash="h",
        page_no=1,
        image_hash="img",
        provider_name="gemini",
        model_name="gemini-2.5-flash",
        schema_version="case-boundary-v2",
    )

    assert key_v1 != key_v2


def test_vision_cache_prevents_duplicate_provider_call(tmp_path, monkeypatch):
    rendered = _rendered(tmp_path)
    monkeypatch.setattr(detect_module, "extract_page_text", lambda *_: "")

    provider = StubVisionProvider(
        PageVisionResult(
            case_blocks=[CaseBlock(case_number="2025타경1708", confidence=0.95, y_top=0.1, y_bottom=0.8)],
            review_required=False,
            source="gemini",
        )
    )
    cache = VisionCache(tmp_path / "state")

    first = analyze_page(
        rendered,
        vision_provider=provider,
        vision_cache=cache,
        pdf_hash="h1",
        work_dir=tmp_path,
    )
    second = analyze_page(
        rendered,
        vision_provider=provider,
        vision_cache=cache,
        pdf_hash="h1",
        work_dir=tmp_path,
    )

    assert first.case_numbers == ["2025타경1708"]
    assert second.case_numbers == ["2025타경1708"]
    assert provider.calls == 1
    assert second.source == "gemini(cache)"
