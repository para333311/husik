"""텔레그램 대표 메시지 / 업데이트 메시지 텍스트 빌더."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from husik.utils.dates import format_deadline_label
from husik.utils.money import format_money, format_rate

MESSAGE_LIMIT = 3800
DIVIDER = "-" * 20
# 달러 기호 등급은 제목 앞에 그대로 붙이고, 그 외(낮은등급/등급확인)는 대괄호로 감싼다.
DOLLAR_SIGN_RATINGS = {"$$$", "$$$$", "$$$$$"}


@dataclass
class AuctionFields:
    court: str = "확인중"
    address: str = "확인중"
    appraisal_price: int | None = None
    min_price: int | None = None
    sale_date: date | None = None
    status: str = "확인중"
    winning_price: int | None = None
    winning_rate: float | None = None
    bidder_count: int | None = None
    madangs_link: str = "확인중"
    court_link: str = "확인중"


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
    item_number: str = "확인중"
    auction: AuctionFields = field(default_factory=AuctionFields)
    interest: InterestStats = field(default_factory=InterestStats)
    lecture_notes: str = "확인중"
    blog_summary: str = "확인중"
    image_count: int = 0


def auction_fields_from_dict(data: dict) -> AuctionFields:
    """auction.monitor 등이 직렬화해 state에 저장한 dict를 AuctionFields로 복원한다."""
    sale_date_raw = data.get("sale_date")
    sale_date: date | None = None
    if sale_date_raw:
        try:
            sale_date = date.fromisoformat(sale_date_raw)
        except (ValueError, TypeError):
            sale_date = None
    return AuctionFields(
        court=data.get("court") or "확인중",
        address=data.get("address") or "확인중",
        appraisal_price=data.get("appraisal_price"),
        min_price=data.get("min_price"),
        sale_date=sale_date,
        status=data.get("status") or "확인중",
        winning_price=data.get("winning_price"),
        winning_rate=data.get("winning_rate"),
        bidder_count=data.get("bidder_count"),
        madangs_link=data.get("madangs_link") or "확인중",
        court_link=data.get("court_link") or "확인중",
    )


def build_header(data: CaseMessageData, event_tag: str | None = None) -> str:
    deadline = format_deadline_label(data.auction.sale_date)
    rating = data.rating or "등급확인"
    rating_part = rating if rating in DOLLAR_SIGN_RATINGS else f"[{rating}]"
    base = f"[{deadline}] {rating_part} {data.title}"
    return f"[{event_tag}] {base}" if event_tag else base


def build_body(data: CaseMessageData) -> str:
    a = data.auction
    i = data.interest
    lines = [
        f"사건번호: {data.case_number}",
        f"물건번호: {data.item_number}",
        f"법원: {a.court}",
        f"소재지: {a.address}",
        f"감정가: {format_money(a.appraisal_price)}",
        f"최저가: {format_money(a.min_price)}",
        f"매각기일: {a.sale_date.isoformat() if a.sale_date else '확인중'}",
        f"상태: {a.status}",
        "관심도:",
        f"  - 법원경매 조회수: {i.court_views if i.court_views is not None else '확인중'}",
        f"  - 경매마당 조회수: {i.madangs_views if i.madangs_views is not None else '확인중'}",
        f"  - 블로그 언급: {i.blog_mentions}",
        f"  - 최근 7일 신규 블로그: {i.recent_blog_mentions}",
        f"경매마당 링크: {a.madangs_link}",
        f"법원경매 링크: {a.court_link}",
        f"휴식형 강의내용: {data.lecture_notes}",
        f"블로그 분석글: {data.blog_summary}",
        "누적기록: Notion 상세페이지 참고",
        f"이미지 안내: 아래 첨부 이미지 {data.image_count}장 참고",
    ]
    return "\n".join(lines)


def build_award_result_block(data: CaseMessageData) -> str:
    a = data.auction
    lines = [
        f"상태: {a.status}",
        f"감정가: {format_money(a.appraisal_price)}",
        f"최저가: {format_money(a.min_price)}",
        f"낙찰가: {format_money(a.winning_price)}",
        f"낙찰가율: {format_rate(a.winning_rate)}",
        f"입찰인수: {a.bidder_count if a.bidder_count is not None else '확인중'}명",
        f"경매마당 링크: {a.madangs_link}",
    ]
    return "\n".join(lines)


def truncate_message(text: str, limit: int = MESSAGE_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20].rstrip() + "\n...(생략, Notion 참고)"


def build_representative_message(data: CaseMessageData) -> str:
    text = build_header(data) + "\n\n" + build_body(data)
    return truncate_message(text)


def build_event_update(event_tag: str, data: CaseMessageData, existing_message: str) -> str:
    """블로그업데이트/상태변경 등 새 이벤트를 맨 위에 붙이고 기존 내용을 아래에 유지한다."""
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
