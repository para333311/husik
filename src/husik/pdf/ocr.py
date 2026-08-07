"""페이지 텍스트 추출: PyMuPDF native 텍스트 -> 영역 OCR(Tesseract) -> OpenAI Vision fallback."""
from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import requests

from husik.utils.text import extract_case_numbers, extract_progress_status, extract_sale_date

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


@dataclass
class VisionCaseResult:
    is_case_start: bool = False
    case_number: str | None = None
    title: str | None = None
    sale_date: date | None = None
    status: str | None = None
    confidence: float = 0.0


def _safe_openai_chat(payload: dict, api_key: str, timeout: int) -> str:
    response = requests.post(
        OPENAI_VISION_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    return (data["choices"][0]["message"]["content"] or "").strip()


def _read_image_as_b64(image_path: Path) -> str:
    return base64.b64encode(image_path.read_bytes()).decode("ascii")


def tesseract_ocr(image_path: Path) -> str:
    if pytesseract is None or Image is None:
        return ""
    try:
        with Image.open(image_path) as img:
            return pytesseract.image_to_string(img, lang="kor+eng")
    except Exception as exc:  # pragma: no cover - depends on system tesseract install
        logger.warning("tesseract OCR failed for %s: %s", image_path.name, exc)
        return ""


def tesseract_ocr_regions(
    image_path: Path, regions: list[tuple[str, tuple[float, float, float, float]]]
) -> dict[str, str]:
    """영역별 OCR. 좌표는 비율(0~1) 기준이며 결과는 영역명->텍스트."""
    if pytesseract is None or Image is None:
        return {name: "" for name, _ in regions}

    outputs: dict[str, str] = {}
    try:
        with Image.open(image_path) as img:
            width, height = img.size
            for name, (x1r, y1r, x2r, y2r) in regions:
                x1 = max(0, min(int(width * x1r), width - 1))
                y1 = max(0, min(int(height * y1r), height - 1))
                x2 = max(x1 + 1, min(int(width * x2r), width))
                y2 = max(y1 + 1, min(int(height * y2r), height))
                crop = img.crop((x1, y1, x2, y2))
                outputs[name] = pytesseract.image_to_string(crop, lang="kor+eng").strip()
    except Exception as exc:  # pragma: no cover
        logger.warning("tesseract region OCR failed for %s: %s", image_path.name, exc)
        return {name: "" for name, _ in regions}

    return outputs


def openai_vision_ocr(image_path: Path, api_key: str, timeout: int = 60) -> str:
    """OPENAI_API_KEY는 호출자에서만 전달되며 이 함수는 값을 로그로 남기지 않는다."""
    if not api_key:
        return ""
    try:
        b64 = _read_image_as_b64(image_path)
        return _safe_openai_chat(
            {
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
            api_key=api_key,
            timeout=timeout,
        )
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
    """텍스트 기반 인식이 불안정할 때 Vision에게 사건번호 목록만 JSON으로 물어본다."""
    if not api_key:
        return []
    try:
        b64 = _read_image_as_b64(image_path)
        content = _safe_openai_chat(
            {
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
            api_key=api_key,
            timeout=timeout,
        )
        parsed = json.loads(content or "{}")
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


VISION_CASE_METADATA_PROMPT = (
    "이 이미지는 경매 정보 PDF의 한 페이지 또는 슬라이드입니다. "
    "아래 JSON 스키마로만 응답하세요. 다른 설명 금지.\n"
    "{\n"
    '  "is_case_start": true/false,\n'
    '  "case_number": "2025타경1708" | null,\n'
    '  "title": "..." | null,\n'
    '  "sale_date": "2026.5.19" | null,\n'
    '  "status": "낙찰|유찰|변경|취하|기각|진행중|매각" | null,\n'
    '  "confidence": 0.0~1.0\n'
    "}\n"
    "주의: 사건번호는 반드시 20xx타경숫자(4~8자리) 형태로만 반환. 불확실하면 null."
)


def openai_vision_case_metadata(image_path: Path, api_key: str, timeout: int = 60) -> VisionCaseResult:
    """사건번호/제목/매각기일/상태만 최소 JSON으로 추출한다. 실패 시 기본값 반환."""
    if not api_key:
        return VisionCaseResult()

    try:
        b64 = _read_image_as_b64(image_path)
        content = _safe_openai_chat(
            {
                "model": OPENAI_VISION_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": VISION_CASE_METADATA_PROMPT},
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
            api_key=api_key,
            timeout=timeout,
        )
        parsed = json.loads(content or "{}")

        case_number = None
        raw_case = parsed.get("case_number")
        if isinstance(raw_case, str):
            extracted = extract_case_numbers(raw_case)
            case_number = extracted[0] if extracted else None

        title = parsed.get("title") if isinstance(parsed.get("title"), str) else None

        sale_date_value: date | None = None
        raw_sale_date = parsed.get("sale_date")
        if isinstance(raw_sale_date, str):
            normalized = extract_sale_date(f"매각기일 {raw_sale_date}")
            if normalized:
                y, m, d = normalized.split(".")
                sale_date_value = date(int(y), int(m), int(d))

        status = None
        raw_status = parsed.get("status")
        if isinstance(raw_status, str):
            status = extract_progress_status(raw_status)

        confidence = parsed.get("confidence", 0.0)
        if not isinstance(confidence, (float, int)):
            confidence = 0.0

        is_case_start = bool(parsed.get("is_case_start"))
        if case_number and confidence >= 0.6:
            is_case_start = True

        return VisionCaseResult(
            is_case_start=is_case_start,
            case_number=case_number,
            title=title.strip() if title else None,
            sale_date=sale_date_value,
            status=status,
            confidence=float(confidence),
        )
    except Exception as exc:
        logger.warning("OpenAI vision case-metadata extraction failed for %s: %s", image_path.name, exc)
        return VisionCaseResult()


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
