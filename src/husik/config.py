"""환경변수 기반 설정 로딩과 검증.

절대 토큰/시크릿 값을 로그로 출력하지 않는다. 값은 os.environ 또는 .env(로컬 전용)에서만 읽는다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency guard
    load_dotenv = None  # type: ignore[assignment]

# 시크릿류 필수 환경변수 (NOTION_AUCTION_DB_URL은 fallback이 있어 별도 처리)
REQUIRED_ENV_VARS: list[str] = [
    "TELEGRAM_AUCTION_BOT_TOKEN",
    "TELEGRAM_AUDIO_BOT_TOKEN",
    "TELEGRAM_AUCTION_CHANNEL_ID",
    "TELEGRAM_AUDIO_CHANNEL_ID",
    "TELEGRAM_ALLOWED_USER_ID",
    "OPENAI_API_KEY",
    "NOTION_TOKEN",
    "NAVER_CLIENT_ID",
    "NAVER_CLIENT_SECRET",
]

LEGACY_NOTION_DB_VAR = "NOTION_HUSIK_DB_ID"
NOTION_DB_VAR = "NOTION_AUCTION_DB_URL"


def _bool_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


@dataclass
class Config:
    telegram_auction_bot_token: str
    telegram_audio_bot_token: str
    telegram_auction_channel_id: str
    telegram_audio_channel_id: str
    telegram_allowed_user_id: str
    openai_api_key: str
    notion_token: str
    notion_auction_db_url: str
    naver_client_id: str
    naver_client_secret: str
    court_auction_enabled: bool
    madangs_enabled: bool
    blog_monitor_enabled: bool
    state_dir: Path = field(default_factory=lambda: Path("data/state"))
    tmp_dir: Path = field(default_factory=lambda: Path("data/tmp"))

    @classmethod
    def from_env(cls) -> Config:
        notion_db_url = os.environ.get(NOTION_DB_VAR) or os.environ.get(LEGACY_NOTION_DB_VAR, "")
        return cls(
            telegram_auction_bot_token=os.environ.get("TELEGRAM_AUCTION_BOT_TOKEN", ""),
            telegram_audio_bot_token=os.environ.get("TELEGRAM_AUDIO_BOT_TOKEN", ""),
            telegram_auction_channel_id=os.environ.get("TELEGRAM_AUCTION_CHANNEL_ID", ""),
            telegram_audio_channel_id=os.environ.get("TELEGRAM_AUDIO_CHANNEL_ID", ""),
            telegram_allowed_user_id=os.environ.get("TELEGRAM_ALLOWED_USER_ID", ""),
            openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
            notion_token=os.environ.get("NOTION_TOKEN", ""),
            notion_auction_db_url=notion_db_url,
            naver_client_id=os.environ.get("NAVER_CLIENT_ID", ""),
            naver_client_secret=os.environ.get("NAVER_CLIENT_SECRET", ""),
            court_auction_enabled=_bool_env("COURT_AUCTION_ENABLED", True),
            madangs_enabled=_bool_env("MADANGS_ENABLED", True),
            blog_monitor_enabled=_bool_env("BLOG_MONITOR_ENABLED", True),
            state_dir=Path(os.environ.get("HUSIK_STATE_DIR", "data/state")),
            tmp_dir=Path(os.environ.get("HUSIK_TMP_DIR", "data/tmp")),
        )


def load_config() -> Config:
    """환경변수를 로드한다. 로컬 개발 시에만 .env를 함께 읽는다 (커밋 금지 파일)."""
    if load_dotenv is not None:
        load_dotenv(override=False)
    return Config.from_env()


@dataclass
class EnvCheckResult:
    missing: list[str]

    @property
    def ok(self) -> bool:
        return not self.missing


def validate_env() -> EnvCheckResult:
    """필수 환경변수 존재 여부만 검사한다. 값 자체는 반환/출력하지 않는다."""
    missing = [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]
    if not os.environ.get(NOTION_DB_VAR) and not os.environ.get(LEGACY_NOTION_DB_VAR):
        missing.append(f"{NOTION_DB_VAR} (또는 레거시 {LEGACY_NOTION_DB_VAR})")
    return EnvCheckResult(missing=missing)
