"""얇은 Telegram Bot API 클라이언트.

봇 토큰은 절대 로그로 출력하지 않는다 (URL 조합에만 사용).
"""
from __future__ import annotations

import json as _json
import logging
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"
DEFAULT_TIMEOUT = 30


class TelegramError(Exception):
    pass


class TelegramClient:
    def __init__(self, bot_token: str, timeout: int = DEFAULT_TIMEOUT):
        if not bot_token:
            raise ValueError("bot token is required")
        self._token = bot_token
        self.timeout = timeout

    @property
    def _base_url(self) -> str:
        return f"{API_BASE}/bot{self._token}"

    def _call(
        self,
        method: str,
        payload: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self._base_url}/{method}"
        try:
            response = requests.post(url, data=payload, files=files, timeout=self.timeout)
            data = response.json()
        except Exception as exc:
            logger.error("telegram api call %s failed: %s", method, exc)
            raise TelegramError(f"{method} request failed") from exc
        if not data.get("ok"):
            logger.error("telegram api %s returned error: %s", method, data.get("description"))
            raise TelegramError(data.get("description", "unknown telegram error"))
        return data["result"]

    def get_updates(self, offset: int | None = None, timeout: int = 0) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            payload["offset"] = offset
        return self._call("getUpdates", payload)

    def get_file(self, file_id: str) -> dict[str, Any]:
        return self._call("getFile", {"file_id": file_id})

    def download_file(self, file_path: str, dest: Path) -> Path:
        url = f"{API_BASE}/file/bot{self._token}/{file_path}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        with requests.get(url, stream=True, timeout=self.timeout) as response:
            response.raise_for_status()
            with dest.open("wb") as f:
                for chunk in response.iter_content(chunk_size=1 << 16):
                    f.write(chunk)
        return dest

    def send_message(
        self, chat_id: str | int, text: str, reply_to_message_id: int | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        return self._call("sendMessage", payload)

    def edit_message_text(self, chat_id: str | int, message_id: int, text: str) -> dict[str, Any]:
        return self._call(
            "editMessageText",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "disable_web_page_preview": True,
            },
        )

    def send_photo(
        self,
        chat_id: str | int,
        photo_path: Path,
        caption: str = "",
        reply_to_message_id: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"chat_id": chat_id, "caption": caption}
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        with photo_path.open("rb") as f:
            return self._call("sendPhoto", payload, files={"photo": f})

    def send_media_group(
        self,
        chat_id: str | int,
        photo_paths: list[Path],
        captions: list[str] | None = None,
        reply_to_message_id: int | None = None,
    ) -> list[dict[str, Any]]:
        media = []
        files: dict[str, Any] = {}
        try:
            for i, path in enumerate(photo_paths):
                key = f"photo{i}"
                files[key] = path.open("rb")
                item: dict[str, Any] = {"type": "photo", "media": f"attach://{key}"}
                if captions and i < len(captions) and captions[i]:
                    item["caption"] = captions[i]
                media.append(item)
            payload: dict[str, Any] = {"chat_id": chat_id, "media": _json.dumps(media)}
            if reply_to_message_id:
                payload["reply_to_message_id"] = reply_to_message_id
            return self._call("sendMediaGroup", payload, files=files)
        finally:
            for f in files.values():
                f.close()
