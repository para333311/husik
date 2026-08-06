"""법원경매정보(courtauction.go.kr) best-effort adapter.

정확한 사건 상세 페이지는 JS 기반 세션/POST 검색이라 안정적으로 생성하기 어려워,
접근 가능한 범위에서 검색 진입 링크만 채운다. 상세 데이터 파싱은 이후 단계 확장 지점.
"""
from __future__ import annotations

import logging
from urllib.parse import quote

import requests

from husik.auction.adapters import AuctionInfo

logger = logging.getLogger(__name__)

COURT_AUCTION_MAIN_URL = "https://www.courtauction.go.kr"


class CourtAuctionAdapter:
    name = "court_auction"

    def fetch(self, case_number: str) -> AuctionInfo:
        link = f"{COURT_AUCTION_MAIN_URL}/pgj/index.on#/search?srchNm={quote(case_number)}"
        info = AuctionInfo(court_link=link, status="확인중")
        try:
            response = requests.get(COURT_AUCTION_MAIN_URL, timeout=10)
            if response.status_code != 200:
                logger.info("court auction site returned status=%s", response.status_code)
        except Exception as exc:
            logger.info("court auction site unreachable: %s", exc)
        return info
