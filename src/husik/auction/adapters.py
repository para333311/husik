"""경매정보 보강 adapter 공통 인터페이스.

로그인 우회/CAPTCHA 우회/비정상 크롤링은 하지 않는다. 조회/파싱 실패는
전체 플로우를 막지 않고 AuctionInfo의 해당 필드를 비워(None) 둔다.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import date
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass
class AuctionInfo:
    court: str | None = None
    address: str | None = None
    appraisal_price: int | None = None
    min_price: int | None = None
    sale_date: date | None = None
    status: str | None = None
    winning_price: int | None = None
    winning_rate: float | None = None
    bidder_count: int | None = None
    court_views: int | None = None
    madangs_views: int | None = None
    madangs_link: str | None = None
    court_link: str | None = None

    def merge(self, other: AuctionInfo) -> AuctionInfo:
        """other에 값이 있는 필드만 덮어써서 병합한다."""
        data = asdict(self)
        for key, value in asdict(other).items():
            if value is not None:
                data[key] = value
        return AuctionInfo(**data)


class AuctionAdapter(Protocol):
    name: str

    def fetch(self, case_number: str) -> AuctionInfo: ...


def safe_fetch(adapter: AuctionAdapter, case_number: str) -> AuctionInfo:
    try:
        return adapter.fetch(case_number)
    except Exception as exc:
        logger.warning("%s adapter failed for %s: %s", getattr(adapter, "name", adapter), case_number, exc)
        return AuctionInfo()
