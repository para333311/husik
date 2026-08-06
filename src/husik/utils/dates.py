"""날짜 파싱 및 입찰 D-day 라벨 포맷 유틸리티."""
from __future__ import annotations

import re
from datetime import date

DATE_PATTERN = re.compile(r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})")


def parse_date(text: str) -> date | None:
    match = DATE_PATTERN.search(text or "")
    if not match:
        return None
    year, month, day = (int(x) for x in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def format_deadline_label(sale_date: date | None, today: date | None = None) -> str:
    """대표 메시지 헤더에 쓰이는 "2026-08-20 입찰 D-14" / "입찰일 확인중" 라벨을 만든다."""
    if sale_date is None:
        return "입찰일 확인중"
    today = today or date.today()
    delta = (sale_date - today).days
    dday = f"D-{delta}" if delta >= 0 else f"D+{abs(delta)}"
    return f"{sale_date.isoformat()} 입찰 {dday}"
