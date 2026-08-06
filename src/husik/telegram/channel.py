"""출력 채널(TELEGRAM_AUCTION_CHANNEL_ID) 형식 검증 및 접근 진단.

채널 ID는 보통 -100으로 시작하는 슈퍼그룹/채널 ID다. 봇 ID나 사용자 ID(양수)를
잘못 넣는 실수를 조기에 잡아내기 위한 검증과, 실제 봇이 그 채널에 메시지를
보낼 권한이 있는지 확인하는 진단 기능을 제공한다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from husik.telegram.client import TelegramClient, TelegramError

logger = logging.getLogger(__name__)

SYSTEM_TEST_MESSAGE = "[시스템테스트] husik 채널 접근 진단 메시지입니다. 자동으로 삭제됩니다."


def validate_channel_id(channel_id: str | None) -> tuple[bool, str]:
    """형식만 검사한다 (실제 네트워크 호출 없음). (is_valid, 사유) 를 반환한다."""
    cid = (channel_id or "").strip()
    if not cid:
        return False, "TELEGRAM_AUCTION_CHANNEL_ID가 비어 있습니다."
    if cid.startswith("@"):
        return True, "공개 채널 사용자명 형식입니다."

    digits = cid[1:] if cid.startswith("-") else cid
    if digits.isdigit():
        if cid.startswith("-100"):
            return True, "정상적인 채널/슈퍼그룹 ID 형식입니다 (-100...)."
        if cid.startswith("-"):
            return (
                False,
                "채널/슈퍼그룹 ID는 보통 -100으로 시작합니다. 일반 그룹 ID일 수 있으니 확인하세요.",
            )
        return (
            False,
            "채널 ID가 양수입니다. 봇 ID나 사용자 ID를 잘못 넣었을 가능성이 높습니다. "
            "채널 ID는 -100으로 시작해야 합니다.",
        )
    return False, "채널 ID 형식을 인식할 수 없습니다."


@dataclass
class ChannelDiagnosis:
    chat_ok: bool = False
    chat_title: str | None = None
    send_ok: bool = False
    delete_ok: bool = False
    error: str | None = None


def diagnose_channel_access(telegram: TelegramClient, channel_id: str) -> ChannelDiagnosis:
    """getChat과 테스트 send/delete로 봇이 출력 채널에 접근 가능한지 확인한다.

    삭제 권한이 없으면 [시스템테스트] 메시지 1개가 채널에 남을 수 있다 (README에 명시).
    """
    diag = ChannelDiagnosis()
    try:
        chat = telegram.get_chat(channel_id)
        diag.chat_ok = True
        diag.chat_title = chat.get("title") or chat.get("username")
    except TelegramError as exc:
        diag.error = str(exc)
        return diag

    try:
        sent = telegram.send_message(channel_id, SYSTEM_TEST_MESSAGE)
        diag.send_ok = True
        try:
            telegram.delete_message(channel_id, sent["message_id"])
            diag.delete_ok = True
        except TelegramError as exc:
            logger.warning("채널 진단 메시지를 삭제하지 못했습니다 (권한 부족일 수 있음): %s", exc)
    except TelegramError as exc:
        diag.error = str(exc)

    return diag
