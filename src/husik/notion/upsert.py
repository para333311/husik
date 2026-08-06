"""사건번호 기준 Notion 페이지 upsert."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from husik.notion.client import NotionClient
from husik.notion.schema import ensure_schema
from husik.utils.text import rating_to_count

logger = logging.getLogger(__name__)


@dataclass
class NotionCaseData:
    case_number: str
    title: str
    rating: str
    item_number: str
    court: str
    address: str
    appraisal_price: int | None
    min_price: int | None
    sale_date: date | None
    status: str
    winning_price: int | None
    winning_rate: float | None
    bidder_count: int | None
    court_views: int | None
    madangs_views: int | None
    blog_mentions: int
    recent_blog_mentions: int
    madangs_link: str
    court_link: str
    telegram_message_link: str


def _num(value: int | float | None) -> dict[str, Any]:
    return {"number": value}


def _rich(value: str) -> dict[str, Any]:
    return {"rich_text": [{"type": "text", "text": {"content": (value or "")[:1900]}}]}


def _url(value: str | None) -> dict[str, Any]:
    return {"url": value if value and value.startswith("http") else None}


def _date(value: date | None) -> dict[str, Any]:
    return {"date": {"start": value.isoformat()} if value else None}


def build_properties(data: NotionCaseData, name_map: dict[str, str], today: date) -> dict[str, Any]:
    return {
        name_map["제목"]: {"title": [{"type": "text", "text": {"content": data.title[:200]}}]},
        "달러등급": {"select": {"name": data.rating}},
        "달러개수": _num(rating_to_count(data.rating)),
        "사건번호": _rich(data.case_number),
        "물건번호": _rich(data.item_number),
        "법원": _rich(data.court),
        "소재지": _rich(data.address),
        "감정가": _num(data.appraisal_price),
        "최저가": _num(data.min_price),
        "매각기일": _date(data.sale_date),
        "상태": _rich(data.status),
        "낙찰가": _num(data.winning_price),
        "낙찰가율": _num(data.winning_rate),
        "입찰인수": _num(data.bidder_count),
        "법원경매 조회수": _num(data.court_views),
        "경매마당 조회수": _num(data.madangs_views),
        "블로그 언급수": _num(data.blog_mentions),
        "최근 7일 블로그 언급수": _num(data.recent_blog_mentions),
        "경매마당 링크": _url(data.madangs_link),
        "법원경매 링크": _url(data.court_link),
        "텔레그램 대표 메시지 링크": _url(data.telegram_message_link),
        "마지막 확인일": _date(today),
    }


def find_existing_page(client: NotionClient, database_id: str, case_number: str) -> dict[str, Any] | None:
    results = client.query_database(
        database_id, {"property": "사건번호", "rich_text": {"equals": case_number}}
    )
    return results[0] if results else None


def upsert_case_page(
    client: NotionClient,
    database_id: str,
    data: NotionCaseData,
    log_lines: list[str] | None = None,
) -> str:
    """사건번호로 기존 페이지를 찾아 업데이트하거나, 없으면 새로 만든다.

    본문에는 대표 메시지 내용/블로그 링크/상태변경 기록을 append 방식으로 누적한다.
    """
    name_map = ensure_schema(client, database_id)
    today = date.today()
    existing = find_existing_page(client, database_id, data.case_number)
    properties = build_properties(data, name_map, today)

    if existing:
        page_id = existing["id"]
        client.update_page(page_id, properties)
    else:
        properties["등록일"] = _date(today)
        page = client.create_page(database_id, properties)
        page_id = page["id"]

    if log_lines:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        content = f"[{timestamp}]\n" + "\n".join(log_lines)
        children = [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": content[:1900]}}]},
            },
            {"object": "block", "type": "divider", "divider": {}},
        ]
        try:
            client.append_blocks(page_id, children)
        except Exception as exc:
            logger.warning("failed to append notion blocks for %s: %s", data.case_number, exc)

    return page_id
