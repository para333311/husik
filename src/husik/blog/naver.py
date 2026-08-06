"""네이버 블로그 검색 API 연동.

NAVER_CLIENT_ID/SECRET은 절대 로그로 출력하지 않는다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

API_URL = "https://openapi.naver.com/v1/search/blog.json"


@dataclass
class BlogPost:
    title: str
    link: str
    post_date: str


def _strip_tags(text: str) -> str:
    return text.replace("<b>", "").replace("</b>", "").replace("&quot;", '"').replace("&amp;", "&")


def search_blog(client_id: str, client_secret: str, query: str, display: int = 10) -> list[BlogPost]:
    if not client_id or not client_secret or not query.strip():
        return []
    try:
        response = requests.get(
            API_URL,
            headers={"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret},
            params={"query": query, "display": display, "sort": "date"},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        logger.warning("naver blog search failed for query %r: %s", query, exc)
        return []

    posts = []
    for item in data.get("items", []):
        link = item.get("link", "")
        if not link:
            continue
        posts.append(
            BlogPost(
                title=_strip_tags(item.get("title", "")),
                link=link,
                post_date=item.get("postdate", ""),
            )
        )
    return posts
