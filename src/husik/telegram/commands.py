"""경매봇 개인대화방 진단용 슬래시 명령 (/ping, /whoami, /chatid).

TELEGRAM_ALLOWED_USER_ID / TELEGRAM_AUCTION_CHANNEL_ID를 설정하기 전에도
사용자가 자기 user_id/chat_id를 알아낼 수 있어야 하므로, 허용 사용자 여부와
무관하게 개인대화방에서 항상 응답한다. PDF 처리 로직과 무관하게 항상 즉시 응답한다.
"""
from __future__ import annotations


def parse_command(text: str | None) -> str | None:
    """"/ping@my_bot 인자" 같은 형태에서 명령어만 뽑아낸다."""
    if not text or not text.startswith("/"):
        return None
    first_token = text.strip().split()[0]
    return first_token.split("@")[0].lower()


def handle_bot_command(text: str | None, user_id: int | str | None, chat_id: int | str | None) -> str | None:
    """명령이 아니거나 지원하지 않는 명령이면 None을 반환한다."""
    command = parse_command(text)
    if command is None:
        return None
    if command == "/ping":
        return "pong"
    if command == "/whoami":
        return f"user_id: {user_id}"
    if command == "/chatid":
        return f"chat_id: {chat_id}"
    return None
