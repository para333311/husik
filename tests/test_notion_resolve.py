from husik.notion.client import NotionError
from husik.notion.schema import resolve_database_id


class FakeNotionClient:
    def __init__(self, retrieve_ok: bool, search_results):
        self.retrieve_ok = retrieve_ok
        self.search_results = search_results
        self.retrieved_ids = []
        self.search_queries = []

    def retrieve_database(self, database_id):
        self.retrieved_ids.append(database_id)
        if not self.retrieve_ok:
            raise NotionError("not found")
        return {"id": database_id, "properties": {}}

    def search_databases(self, query):
        self.search_queries.append(query)
        return self.search_results


def test_resolve_database_id_uses_configured_url_when_valid():
    client = FakeNotionClient(retrieve_ok=True, search_results=[])
    result = resolve_database_id(client, "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d")
    assert result == "1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d"
    assert client.search_queries == []


def test_resolve_database_id_falls_back_to_search_when_configured_url_fails():
    client = FakeNotionClient(retrieve_ok=False, search_results=[{"id": "found-db-id"}])
    result = resolve_database_id(client, "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d")
    assert result == "found-db-id"
    assert client.search_queries == ["매수맛집 경매"]


def test_resolve_database_id_falls_back_to_search_when_no_url_configured():
    client = FakeNotionClient(retrieve_ok=False, search_results=[{"id": "found-db-id"}])
    result = resolve_database_id(client, "")
    assert result == "found-db-id"


def test_resolve_database_id_returns_none_when_everything_fails():
    client = FakeNotionClient(retrieve_ok=False, search_results=[])
    result = resolve_database_id(client, "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d")
    assert result is None
