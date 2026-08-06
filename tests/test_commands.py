from husik.telegram.commands import handle_bot_command, parse_command


def test_parse_command_strips_bot_username_suffix():
    assert parse_command("/ping@my_bot") == "/ping"


def test_parse_command_none_for_non_command_text():
    assert parse_command("hello") is None
    assert parse_command(None) is None


def test_ping_returns_pong():
    assert handle_bot_command("/ping", user_id=111, chat_id=222) == "pong"


def test_whoami_returns_user_id():
    response = handle_bot_command("/whoami", user_id=111, chat_id=222)
    assert response is not None
    assert "111" in response


def test_chatid_returns_chat_id():
    response = handle_bot_command("/chatid", user_id=111, chat_id=222)
    assert response is not None
    assert "222" in response


def test_unknown_command_returns_none():
    assert handle_bot_command("/unknown", user_id=1, chat_id=2) is None


def test_non_command_text_returns_none():
    assert handle_bot_command("일반 메시지", user_id=1, chat_id=2) is None
