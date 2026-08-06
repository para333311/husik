"""페이지 텍스트 추출: PyMuPDF native 텍스트 -> Tesseract(kor+eng) -> OpenAI Vision fallback."""
from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

import requests

from husik.utils.text import extract_case_numbers

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


VISION_CASE_NUMBER_PROMPT = (
    "이 이미지는 경매 정보 PDF의 한 페이지입니다. "
    '이미지에서 보이는 경매 사건번호(예: "2025타경102095", 20xx타경xxxxx 형식)를 '
    '모두 찾아 JSON으로만 응답하세요. 형식: {"case_numbers": ["2025타경102095"]}. '
    '사건번호가 없으면 {"case_numbers": []}로 응답하세요. 설명은 넣지 마세요.'
)


def openai_vision_case_numbers(image_path: Path, api_key: str, timeout: int = 60) -> list[str]:
    """텍스트 기반 인식이 불안정할 때, Vision에게 해당 페이지의 사건번호 목록만 JSON으로 물어본다.

    반환값은 항상 extract_case_numbers로 재검증된(정규식 형식이 확인된) 사건번호만 포함한다 —
    모델 출력을 무조건 신뢰하지 않는다.
    """
    if not api_key:
        return []
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
                            {"type": "text", "text": VISION_CASE_NUMBER_PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                            },
                        ],
                    }
                ],
                "max_tokens": 300,
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        content = (data["choices"][0]["message"]["content"] or "{}").strip()
        parsed = json.loads(content)
        raw_numbers = parsed.get("case_numbers", [])
        if not isinstance(raw_numbers, list):
            return []

        found: list[str] = []
        for item in raw_numbers:
            if not isinstance(item, str):
                continue
            for case_number in extract_case_numbers(item):
                if case_number not in found:
                    found.append(case_number)
        return found
    except Exception as exc:
        logger.warning("OpenAI vision case-number extraction failed for %s: %s", image_path.name, exc)
        return []


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
