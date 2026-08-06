from husik.notion.client import extract_database_id


def test_extract_database_id_from_dashed_url():
    url = "https://www.notion.so/myworkspace/매수맛집-경매-1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d?v=xyz"
    result = extract_database_id(url)
    assert result == "1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d"


def test_extract_database_id_from_raw_id():
    raw = "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d"
    result = extract_database_id(raw)
    assert result == "1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d"


def test_extract_database_id_passthrough_when_no_match():
    assert extract_database_id("not-a-valid-id") == "not-a-valid-id"


def test_extract_database_id_from_simple_notion_so_url():
    url = "https://www.notion.so/1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d?v=abcdef"
    assert extract_database_id(url) == "1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d"


def test_extract_database_id_from_app_notion_com_url():
    url = "https://app.notion.com/p/1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d?v=abcdef"
    assert extract_database_id(url) == "1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d"


def test_extract_database_id_from_already_dashed_id():
    dashed = "1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d"
    assert extract_database_id(dashed) == dashed
