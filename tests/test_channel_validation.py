from husik.telegram.channel import validate_channel_id


def test_positive_channel_id_is_invalid():
    valid, reason = validate_channel_id("123456789")
    assert valid is False
    assert "양수" in reason


def test_minus100_channel_id_is_valid():
    valid, reason = validate_channel_id("-1001234567890")
    assert valid is True


def test_public_username_channel_id_is_valid():
    valid, _ = validate_channel_id("@my_channel")
    assert valid is True


def test_empty_channel_id_is_invalid():
    valid, reason = validate_channel_id("")
    assert valid is False
    assert "비어" in reason


def test_plain_negative_non_100_channel_id_is_flagged():
    valid, reason = validate_channel_id("-123456789")
    assert valid is False
    assert "-100" in reason
