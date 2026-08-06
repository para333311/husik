""""매수맛집 경매" Notion DB에 필요한 속성을 확인/자동 생성한다."""
from __future__ import annotations

import logging
from typing import Any

from husik.notion.client import NotionClient, NotionError

logger = logging.getLogger(__name__)

TITLE_PROP = "제목"

REQUIRED_PROPERTIES: dict[str, dict[str, Any]] = {
    "제목": {"title": {}},
    "달러등급": {"select": {"options": [{"name": n} for n in ["$$$", "$$$$", "$$$$$", "$$$$$$"]]}},
    "달러개수": {"number": {}},
    "사건번호": {"rich_text": {}},
    "물건번호": {"rich_text": {}},
    "법원": {"rich_text": {}},
    "소재지": {"rich_text": {}},
    "감정가": {"number": {}},
    "최저가": {"number": {}},
    "매각기일": {"date": {}},
    "상태": {"rich_text": {}},
    "낙찰가": {"number": {}},
    "낙찰가율": {"number": {}},
    "입찰인수": {"number": {}},
    "법원경매 조회수": {"number": {}},
    "경매마당 조회수": {"number": {}},
    "블로그 언급수": {"number": {}},
    "최근 7일 블로그 언급수": {"number": {}},
    "경매마당 링크": {"url": {}},
    "법원경매 링크": {"url": {}},
    "텔레그램 대표 메시지 링크": {"url": {}},
    "등록일": {"date": {}},
    "마지막 확인일": {"date": {}},
}


def ensure_schema(client: NotionClient, database_id: str) -> dict[str, str]:
    """필요한 속성이 없으면 자동 생성하고, logical name -> 실제 속성명 매핑을 반환한다.

    title 타입 속성은 DB당 하나만 존재할 수 있어, 이미 다른 이름의 title 속성이 있으면
    그 이름을 그대로 사용한다 (새로 만들지 않는다).
    """
    try:
        db = client.retrieve_database(database_id)
    except NotionError as exc:
        raise NotionError(
            "Notion DB('매수맛집 경매')에 접근할 수 없습니다. "
            "NOTION_AUCTION_DB_URL/NOTION_TOKEN 및 인테그레이션 공유 권한을 확인하세요: "
            f"{exc}"
        ) from exc

    existing = db.get("properties", {})
    existing_title_name = next(
        (name for name, schema in existing.items() if schema.get("type") == "title"),
        None,
    )

    to_create = {
        name: schema
        for name, schema in REQUIRED_PROPERTIES.items()
        if name != TITLE_PROP and name not in existing
    }
    if to_create:
        try:
            client.update_database(database_id, to_create)
            logger.info("added missing notion properties: %s", ", ".join(to_create.keys()))
        except NotionError as exc:
            raise NotionError(
                "Notion DB에 필요한 속성을 자동 생성하지 못했습니다. 다음 속성을 수동으로 추가하세요: "
                + ", ".join(to_create.keys())
            ) from exc

    name_map = {name: name for name in REQUIRED_PROPERTIES}
    if existing_title_name and existing_title_name != TITLE_PROP:
        name_map[TITLE_PROP] = existing_title_name
    return name_map
