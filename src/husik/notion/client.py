"""얇은 Notion REST API 클라이언트.

NOTION_TOKEN은 절대 로그로 출력하지 않는다.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import requests

logger = logging.getLogger(__name__)

API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
UUID_RE = re.compile(r"[0-9a-fA-F]{32}")


class NotionError(Exception):
    pass


class NotionClient:
    def __init__(self, token: str, timeout: int = 30):
        if not token:
            raise ValueError("notion token is required")
        self._token = token
        self.timeout = timeout

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, json_body: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{API_BASE}{path}"
        try:
            response = requests.request(
                method, url, headers=self._headers, json=json_body, timeout=self.timeout
            )
        except Exception as exc:
            raise NotionError(f"notion request failed: {exc}") from exc
        if response.status_code >= 400:
            logger.error(
                "notion api error %s on %s %s: %s",
                response.status_code,
                method,
                path,
                response.text[:500],
            )
            raise NotionError(f"notion api error {response.status_code} on {method} {path}")
        return response.json()

    def retrieve_database(self, database_id: str) -> dict[str, Any]:
        return self._request("GET", f"/databases/{database_id}")

    def update_database(self, database_id: str, properties: dict[str, Any]) -> dict[str, Any]:
        return self._request("PATCH", f"/databases/{database_id}", {"properties": properties})

    def query_database(
        self, database_id: str, filter_obj: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {"filter": filter_obj} if filter_obj else {}
        result = self._request("POST", f"/databases/{database_id}/query", body)
        return result.get("results", [])

    def create_page(
        self, database_id: str, properties: dict[str, Any], children: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"parent": {"database_id": database_id}, "properties": properties}
        if children:
            body["children"] = children
        return self._request("POST", "/pages", body)

    def update_page(self, page_id: str, properties: dict[str, Any]) -> dict[str, Any]:
        return self._request("PATCH", f"/pages/{page_id}", {"properties": properties})

    def append_blocks(self, block_id: str, children: list[dict[str, Any]]) -> dict[str, Any]:
        return self._request("PATCH", f"/blocks/{block_id}/children", {"children": children})


def extract_database_id(url_or_id: str) -> str:
    """Notion DB URL 또는 raw id에서 dash 포함 database_id를 뽑아낸다."""
    if not url_or_id:
        raise ValueError("empty notion database url/id")
    match = UUID_RE.search(url_or_id.replace("-", ""))
    if not match:
        return url_or_id
    raw = match.group(0)
    return f"{raw[0:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"
