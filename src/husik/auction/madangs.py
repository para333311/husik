"""경매마당(madangs) best-effort adapter.

정확한 사건 상세 URL 규칙을 알 수 없어, 검색/메인 링크를 채우는 수준으로 동작한다.
조회 실패는 예외로 전파하지 않고 링크만 채운 AuctionInfo를 반환한다.
"""
from __future__ import annotations

import logging
from urllib.parse import quote

import requests

from husik.auction.adapters import AuctionInfo

logger = logging.getLogger(__name__)

MADANGS_MAIN_URL = "https://www.madangs.com"


class MadangsAdapter:
    name = "madangs"

    def fetch(self, case_number: str) -> AuctionInfo:
        link = f"{MADANGS_MAIN_URL}/search?keyword={quote(case_number)}"
        info = AuctionInfo(madangs_link=link)
        try:
            response = requests.get(MADANGS_MAIN_URL, timeout=10)
            if response.status_code != 200:
                logger.info("madangs site returned status=%s", response.status_code)
        except Exception as exc:
            logger.info("madangs site unreachable: %s", exc)
        return info
