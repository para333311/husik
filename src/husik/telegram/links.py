"""Private 채널 메시지 딥링크 생성.

channel_id가 -1001234567890이면 https://t.me/c/1234567890/message_id 형식으로 만든다.
"""
from __future__ import annotations


def private_channel_message_link(channel_id: str | int, message_id: int) -> str:
    cid = str(channel_id).strip()
    if cid.startswith("-100"):
        numeric = cid[4:]
        return f"https://t.me/c/{numeric}/{message_id}"
    if cid.startswith("@"):
        return f"https://t.me/{cid[1:]}/{message_id}"
    if cid.startswith("-"):
        numeric = cid.lstrip("-")
        return f"https://t.me/c/{numeric}/{message_id}"
    return f"https://t.me/{cid}/{message_id}"
