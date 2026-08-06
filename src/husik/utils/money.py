"""금액/비율 파싱 및 표시 포맷 유틸리티."""
from __future__ import annotations

import re

MONEY_PATTERN = re.compile(r"\d[\d,]*")


def parse_money(text: str) -> int | None:
    if not text:
        return None
    match = MONEY_PATTERN.search(text.replace(" ", ""))
    if not match:
        return None
    digits = match.group(0).replace(",", "")
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def format_money(value: int | None) -> str:
    if value is None:
        return "확인중"
    return f"{value:,}원"


def format_rate(value: float | None) -> str:
    if value is None:
        return "확인중"
    return f"{value:.1f}%"
