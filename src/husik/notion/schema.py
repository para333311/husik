""""매수맛집 경매" Notion DB에 필요한 속성을 확인/자동 생성한다."""
from __future__ import annotations

import logging
from typing import Any

from husik.notion.client import NotionClient, NotionError, extract_database_id

logger = logging.getLogger(__name__)

TITLE_PROP = "제목"
DATABASE_DISPLAY_NAME = "매수맛집 경매"

REQUIRED_PROPERTIES: dict[str, dict[str, Any]] = {
    "제목": {"title": {}},
    "달러등급": {
        "select": {"options": [{"name": n} for n in ["$$$$$", "$$$$", "$$$", "낮은등급", "등급확인"]]}
    },
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


def resolve_database_id(client: NotionClient, configured_db_url_or_id: str) -> str | None:
    """NOTION_AUCTION_DB_URL(or 레거시 NOTION_HUSIK_DB_ID)로 접근을 시도하고,
    실패하면 Notion 검색 API로 "매수맛집 경매" DB를 찾는 fallback을 시도한다.

    Integration 미연결/권한 없음/URL 오류를 구분해 로그로 남기며, 완전히 실패하면
    None을 반환한다 (호출자는 이를 "노션 업데이트 실패"로 처리하되 Telegram 전송은
    막지 않아야 한다).
    """
    if configured_db_url_or_id:
        try:
            db_id = extract_database_id(configured_db_url_or_id)
            client.retrieve_database(db_id)
            return db_id
        except NotionError as exc:
            logger.warning(
                "설정된 NOTION_AUCTION_DB_URL로 DB에 접근하지 못했습니다 "
                "(URL 오류 또는 integration 미공유 가능성). 이름 검색으로 재시도합니다: %s",
                exc,
            )
    else:
        logger.warning("NOTION_AUCTION_DB_URL이 설정되어 있지 않습니다. 이름 검색으로 시도합니다.")

    try:
        results = client.search_databases(DATABASE_DISPLAY_NAME)
    except NotionError as exc:
        logger.error(
            "Notion 검색 API 호출도 실패했습니다. NOTION_TOKEN 값과 integration 연결을 확인하세요: %s",
            exc,
        )
        return None

    if not results:
        logger.error(
            "이름으로 '%s' 데이터베이스를 찾지 못했습니다. "
            "Notion에서 해당 DB에 integration을 공유했는지 확인하세요.",
            DATABASE_DISPLAY_NAME,
        )
        return None

    return results[0]["id"]
