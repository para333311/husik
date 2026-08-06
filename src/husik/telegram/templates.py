"""텔레그램 대표 메시지 / 업데이트 메시지 텍스트 빌더.

가독성을 위해 값이 없는 항목("확인중"/None/0)은 아예 줄을 숨기고, 핵심 항목만
보여준다. "확인중"은 상태/입찰일/등급처럼 꼭 필요한 곳에만 최소로 쓴다.
링크는 긴 URL을 그대로 노출하지 않고 HTML 앵커(<a href="...">텍스트</a>)로
감싼다 — 호출자는 반드시 parse_mode="HTML"로 전송해야 한다.
"""
from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import date

from husik.utils.dates import format_deadline_label
from husik.utils.money import format_money, format_rate

MESSAGE_LIMIT = 3800
DIVIDER = "-" * 20
UNKNOWN = "확인중"
# 달러 기호 등급은 제목 앞에 그대로 붙이고, 그 외(낮은등급/등급확인)는 대괄호로 감싼다.
DOLLAR_SIGN_RATINGS = {"$$$", "$$$$", "$$$$$"}


def _is_known(value: str | None) -> bool:
    return bool(value) and value != UNKNOWN


def _esc(value: object) -> str:
    """parse_mode=HTML로 보내므로, OCR/외부에서 온 자유 텍스트는 반드시 이스케이프한다."""
    return html.escape(str(value), quote=False)


def _esc_attr(value: str) -> str:
    return html.escape(value, quote=True)


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
    item_number: str = UNKNOWN
    auction: AuctionFields = field(default_factory=AuctionFields)
    interest: InterestStats = field(default_factory=InterestStats)
    lecture_notes: str = UNKNOWN
    blog_summary: str = UNKNOWN
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
    deadline = format_deadline_label(data.auction.sale_date)
    rating = data.rating or "등급확인"
    rating_part = rating if rating in DOLLAR_SIGN_RATINGS else f"[{_esc(rating)}]"
    base = f"[{deadline}] {rating_part} {_esc(data.case_number)}"
    return f"[{_esc(event_tag)}] {base}" if event_tag else base


def build_body(data: CaseMessageData, update_log: list[str] | None = None) -> str:
    a = data.auction
    i = data.interest
    lines: list[str] = [f"사건번호: {_esc(data.case_number)}"]

    if data.title and data.title != data.case_number:
        lines.append(f"제목: {_esc(data.title)}")
    if _is_known(data.item_number):
        lines.append(f"물건번호: {_esc(data.item_number)}")
    if _is_known(a.court):
        lines.append(f"법원: {_esc(a.court)}")
    if _is_known(a.address):
        lines.append(f"소재지: {_esc(a.address)}")
    if a.appraisal_price is not None:
        lines.append(f"감정가: {format_money(a.appraisal_price)}")
    if a.min_price is not None:
        lines.append(f"최저가: {format_money(a.min_price)}")
    if a.sale_date is not None:
        lines.append(f"매각기일: {a.sale_date.isoformat()}")
    lines.append(f"상태: {_esc(a.status or UNKNOWN)}")

    interest_lines = []
    if i.court_views is not None:
        interest_lines.append(f"- 법원경매 조회수: {i.court_views}")
    if i.madangs_views is not None:
        interest_lines.append(f"- 경매마당 조회수: {i.madangs_views}")
    if i.blog_mentions:
        interest_lines.append(f"- 블로그 언급: {i.blog_mentions}")
    if i.recent_blog_mentions:
        interest_lines.append(f"- 최근 7일 신규 블로그: {i.recent_blog_mentions}")
    if interest_lines:
        lines.append("")
        lines.append("관심도:")
        lines.extend(interest_lines)

    link_lines = []
    if a.madangs_link and a.madangs_link.startswith("http"):
        link_lines.append(f'- <a href="{_esc_attr(a.madangs_link)}">경매마당</a>')
    if a.court_link and a.court_link.startswith("http"):
        link_lines.append(f'- <a href="{_esc_attr(a.court_link)}">법원경매</a>')
    if link_lines:
        lines.append("")
        lines.append("링크:")
        lines.extend(link_lines)

    lines.append("")
    lines.append(f"첨부 이미지: {data.image_count}장")

    if update_log:
        lines.append("")
        lines.append("업데이트:")
        lines.extend(f"- {_esc(entry)}" for entry in update_log)

    return "\n".join(lines)


def build_award_result_block(data: CaseMessageData) -> str:
    a = data.auction
    lines = [f"상태: {_esc(a.status or UNKNOWN)}"]
    if a.appraisal_price is not None:
        lines.append(f"감정가: {format_money(a.appraisal_price)}")
    if a.min_price is not None:
        lines.append(f"최저가: {format_money(a.min_price)}")
    lines.append(f"낙찰가: {format_money(a.winning_price)}")
    lines.append(f"낙찰가율: {format_rate(a.winning_rate)}")
    lines.append(f"입찰인수: {a.bidder_count if a.bidder_count is not None else UNKNOWN}명")
    if a.madangs_link and a.madangs_link.startswith("http"):
        lines.append(f'경매마당 링크: <a href="{_esc_attr(a.madangs_link)}">경매마당</a>')
    return "\n".join(lines)


def truncate_message(text: str, limit: int = MESSAGE_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20].rstrip() + "\n...(생략, Notion 참고)"


def build_representative_message(data: CaseMessageData) -> str:
    text = build_header(data) + "\n\n" + build_body(data, update_log=["최초 등록"])
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
