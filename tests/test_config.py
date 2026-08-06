from husik.config import validate_env


def _clear_husik_env(monkeypatch):
    for name in [
        "TELEGRAM_AUCTION_BOT_TOKEN",
        "TELEGRAM_AUDIO_BOT_TOKEN",
        "TELEGRAM_AUCTION_CHANNEL_ID",
        "TELEGRAM_AUDIO_CHANNEL_ID",
        "TELEGRAM_ALLOWED_USER_ID",
        "OPENAI_API_KEY",
        "NOTION_TOKEN",
        "NAVER_CLIENT_ID",
        "NAVER_CLIENT_SECRET",
        "NOTION_AUCTION_DB_URL",
        "NOTION_HUSIK_DB_ID",
    ]:
        monkeypatch.delenv(name, raising=False)


def _set_all_required(monkeypatch):
    values = {
        "TELEGRAM_AUCTION_BOT_TOKEN": "x",
        "TELEGRAM_AUDIO_BOT_TOKEN": "x",
        "TELEGRAM_AUCTION_CHANNEL_ID": "x",
        "TELEGRAM_AUDIO_CHANNEL_ID": "x",
        "TELEGRAM_ALLOWED_USER_ID": "x",
        "OPENAI_API_KEY": "x",
        "NOTION_TOKEN": "x",
        "NAVER_CLIENT_ID": "x",
        "NAVER_CLIENT_SECRET": "x",
    }
    for k, v in values.items():
        monkeypatch.setenv(k, v)


def test_validate_env_reports_missing(monkeypatch):
    _clear_husik_env(monkeypatch)
    result = validate_env()
    assert not result.ok
    assert "TELEGRAM_AUCTION_BOT_TOKEN" in result.missing


def test_validate_env_ok_with_notion_auction_db_url(monkeypatch):
    _clear_husik_env(monkeypatch)
    _set_all_required(monkeypatch)
    monkeypatch.setenv("NOTION_AUCTION_DB_URL", "https://notion.so/db123")
    result = validate_env()
    assert result.ok


def test_validate_env_falls_back_to_legacy_notion_db_id(monkeypatch):
    _clear_husik_env(monkeypatch)
    _set_all_required(monkeypatch)
    monkeypatch.setenv("NOTION_HUSIK_DB_ID", "legacy-db-id")
    result = validate_env()
    assert result.ok


def test_config_from_env_prefers_new_notion_var(monkeypatch):
    from husik.config import Config

    _clear_husik_env(monkeypatch)
    _set_all_required(monkeypatch)
    monkeypatch.setenv("NOTION_AUCTION_DB_URL", "new-url")
    monkeypatch.setenv("NOTION_HUSIK_DB_ID", "legacy-id")
    config = Config.from_env()
    assert config.notion_auction_db_url == "new-url"


def test_config_from_env_uses_legacy_when_new_missing(monkeypatch):
    from husik.config import Config

    _clear_husik_env(monkeypatch)
    _set_all_required(monkeypatch)
    monkeypatch.setenv("NOTION_HUSIK_DB_ID", "legacy-id")
    config = Config.from_env()
    assert config.notion_auction_db_url == "legacy-id"
