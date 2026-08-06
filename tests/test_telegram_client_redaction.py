from unittest.mock import patch

import requests

from husik.telegram.client import TelegramClient, TelegramError


def test_network_error_does_not_leak_token_in_exception_message():
    token = "123456:SUPER-SECRET-TOKEN"
    client = TelegramClient(token)

    with patch("husik.telegram.client.requests.post") as mock_post:
        mock_post.side_effect = requests.exceptions.ConnectionError(
            f"Failed to connect to api.telegram.org with url /bot{token}/getMe"
        )
        try:
            client.get_me()
            raised = None
        except TelegramError as exc:
            raised = exc

    assert raised is not None
    assert token not in str(raised)
    assert "***" in str(raised)


def test_download_file_error_does_not_leak_token(tmp_path):
    token = "123456:SUPER-SECRET-TOKEN"
    client = TelegramClient(token)

    with patch("husik.telegram.client.requests.get") as mock_get:
        mock_get.side_effect = requests.exceptions.ConnectionError(
            f"Failed to connect with url /file/bot{token}/foo.pdf"
        )
        try:
            client.download_file("foo.pdf", tmp_path / "out.pdf")
            raised = None
        except TelegramError as exc:
            raised = exc

    assert raised is not None
    assert token not in str(raised)
