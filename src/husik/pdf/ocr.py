"""페이지 텍스트 추출: PyMuPDF native 텍스트 -> Tesseract(kor+eng) -> OpenAI Vision fallback."""
from __future__ import annotations

import base64
import logging
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

try:
    import pytesseract
    from PIL import Image
except ImportError:  # pragma: no cover - optional dependency guard
    pytesseract = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]

OPENAI_VISION_MODEL = "gpt-4o-mini"
OPENAI_VISION_URL = "https://api.openai.com/v1/chat/completions"
MIN_TEXT_LENGTH = 20
VISION_PROMPT = (
    "이 이미지는 경매 정보 PDF의 한 페이지입니다. "
    "이미지에 보이는 모든 텍스트를 줄바꿈을 유지하며 그대로 옮겨 적어주세요. "
    "설명 없이 텍스트만 출력하세요."
)


def tesseract_ocr(image_path: Path) -> str:
    if pytesseract is None or Image is None:
        return ""
    try:
        with Image.open(image_path) as img:
            return pytesseract.image_to_string(img, lang="kor+eng")
    except Exception as exc:  # pragma: no cover - depends on system tesseract install
        logger.warning("tesseract OCR failed for %s: %s", image_path.name, exc)
        return ""


def openai_vision_ocr(image_path: Path, api_key: str, timeout: int = 60) -> str:
    """OPENAI_API_KEY는 호출자에서만 전달되며 이 함수는 값을 로그로 남기지 않는다."""
    if not api_key:
        return ""
    try:
        b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
        response = requests.post(
            OPENAI_VISION_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": OPENAI_VISION_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": VISION_PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                            },
                        ],
                    }
                ],
                "max_tokens": 2000,
                "temperature": 0,
            },
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        return (data["choices"][0]["message"]["content"] or "").strip()
    except Exception as exc:
        logger.warning("OpenAI vision OCR failed for %s: %s", image_path.name, exc)
        return ""


def extract_page_text(image_path: Path, native_text: str, openai_api_key: str | None = None) -> str:
    text = (native_text or "").strip()
    if len(text) >= MIN_TEXT_LENGTH:
        return text

    ocr_text = tesseract_ocr(image_path).strip()
    if len(ocr_text) >= MIN_TEXT_LENGTH:
        return ocr_text

    if openai_api_key:
        vision_text = openai_vision_ocr(image_path, openai_api_key)
        if vision_text:
            return vision_text

    return ocr_text or text
