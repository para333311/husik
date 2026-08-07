"""텔레그램 사건 대표 메시지 텍스트 빌더 (간소화 버전)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from husik.utils.dates import format_compact_date

MESSAGE_LIMIT = 3800
DIVIDER = "-" * 20
UNKNOWN = "확인중"


@dataclass
class AuctionFields:
    court: str = UNKNOWN
    address: str = UNKNOWN
    appraisal_price: int | None = None
    min_price: int | None = None
    sale_date: date | None = None
    status: str = UNKNOWN
    winning_price: int | None = None
    winning_rate: float | None = None
    bidder_count: int | None = None
    madangs_link: str = UNKNOWN
    court_link: str = UNKNOWN


@dataclass
class InterestStats:
    court_views: int | None = None
    madangs_views: int | None = None
    blog_mentions: int = 0
    recent_blog_mentions: int = 0


@dataclass
class CaseMessageData:
    case_number: str
    rating: str
    title: str
    sale_date_text: str | None = None
    status_text: str | None = None
    item_number: str = UNKNOWN
    auction: AuctionFields = field(default_factory=AuctionFields)
    interest: InterestStats = field(default_factory=InterestStats)
    lecture_notes: str = UNKNOWN
    blog_summary: str = UNKNOWN
    image_count: int = 0


def auction_fields_from_dict(data: dict) -> AuctionFields:
    sale_date_raw = data.get("sale_date")
    sale_date: date | None = None
    if sale_date_raw:
        try:
            sale_date = date.fromisoformat(sale_date_raw)
        except (ValueError, TypeError):
            sale_date = None
    return AuctionFields(
        court=data.get("court") or UNKNOWN,
        address=data.get("address") or UNKNOWN,
        appraisal_price=data.get("appraisal_price"),
        min_price=data.get("min_price"),
        sale_date=sale_date,
        status=data.get("status") or UNKNOWN,
        winning_price=data.get("winning_price"),
        winning_rate=data.get("winning_rate"),
        bidder_count=data.get("bidder_count"),
        madangs_link=data.get("madangs_link") or UNKNOWN,
        court_link=data.get("court_link") or UNKNOWN,
    )


def build_header(data: CaseMessageData, event_tag: str | None = None) -> str:
    base = f"[{data.case_number}]"
    return f"[{event_tag}] {base}" if event_tag else base


ALLOWED_STATUS = {"낙찰", "유찰", "변경", "취하", "기각", "진행중", "매각"}


def build_body(data: CaseMessageData, update_log: list[str] | None = None) -> str:
    lines: list[str] = []
    if data.title and data.title != data.case_number:
        lines.append(data.title)

    sale_date = data.sale_date_text or format_compact_date(data.auction.sale_date)
    if sale_date:
        lines.append(f"· 매각기일 {sale_date}")

    status = (data.status_text or data.auction.status or "").strip()
    if status in ALLOWED_STATUS:
        lines.append(f"· {status}")

    return "\n".join(lines)


def build_award_result_block(data: CaseMessageData) -> str:
    return build_body(data)


def truncate_message(text: str, limit: int = MESSAGE_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20].rstrip() + "\n...(생략)"


def build_representative_message(data: CaseMessageData) -> str:
    body = build_body(data)
    text = build_header(data) if not body else build_header(data) + "\n" + body
    return truncate_message(text)


def build_event_update(event_tag: str, data: CaseMessageData, existing_message: str) -> str:
    header = build_header(data, event_tag=event_tag)
    block = header + "\n\n" + build_body(data)
    combined = f"{block}\n{DIVIDER}\n기존 내용\n{existing_message}"
    return truncate_message(combined)


def build_award_update(data: CaseMessageData, existing_message: str) -> str:
    header = build_header(data, event_tag="낙찰결과")
    block = header + "\n\n" + build_award_result_block(data)
    combined = f"{block}\n{DIVIDER}\n기존 내용\n{existing_message}"
    return truncate_message(combined)


def build_page_caption(page_no: int) -> str:
    return f"{page_no}p"
