from husik.telegram.links import private_channel_message_link


def test_private_channel_link_from_minus100_id():
    link = private_channel_message_link("-1001234567890", 42)
    assert link == "https://t.me/c/1234567890/42"


def test_private_channel_link_from_username():
    link = private_channel_message_link("@my_channel", 7)
    assert link == "https://t.me/my_channel/7"


def test_private_channel_link_from_generic_negative_id():
    link = private_channel_message_link("-987654321", 3)
    assert link == "https://t.me/c/987654321/3"
