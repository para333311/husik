from husik.state.store import CaseState, StateStore


def test_roundtrip_offset_and_case(tmp_path):
    store = StateStore(tmp_path)
    store.telegram_offset = 42
    case = CaseState(case_number="2024타경1", representative_message_id=100, image_message_ids=[101, 102])
    store.upsert_case(case)
    store.save()

    reloaded = StateStore(tmp_path)
    assert reloaded.telegram_offset == 42
    loaded_case = reloaded.get_case("2024타경1")
    assert loaded_case is not None
    assert loaded_case.representative_message_id == 100
    assert loaded_case.image_message_ids == [101, 102]


def test_pdf_hash_is_kept_as_reference_history(tmp_path):
    store = StateStore(tmp_path)
    assert not store.has_processed_pdf("abc123")
    store.mark_pdf_processed("abc123", {"file_name": "a.pdf"})
    assert store.has_processed_pdf("abc123")


def test_update_and_message_dedupe_tracking(tmp_path):
    store = StateStore(tmp_path)

    assert not store.has_processed_update(10)
    store.mark_update_processed(10)
    assert store.has_processed_update(10)

    assert not store.has_processed_message(999, 77)
    store.mark_message_processed(999, 77)
    assert store.has_processed_message(999, 77)


def test_missing_case_returns_none(tmp_path):
    store = StateStore(tmp_path)
    assert store.get_case("no-such-case") is None


def test_legacy_state_with_only_hashes_is_compatible(tmp_path):
    state_file = tmp_path / "state.json"
    state_file.write_text(
        '{"telegram_offset": 5, "processed_pdf_hashes": {"h1": {"file_name": "old.pdf"}}, "cases": {}}',
        encoding="utf-8",
    )

    store = StateStore(tmp_path)
    assert store.telegram_offset == 5
    assert store.has_processed_pdf("h1")
    assert not store.has_processed_update(123)
    assert not store.has_processed_message(999, 1)


def test_corrupt_state_file_starts_fresh(tmp_path):
    state_file = tmp_path / "state.json"
    state_file.write_text("not json", encoding="utf-8")
    store = StateStore(tmp_path)
    assert store.telegram_offset == 0
    assert store.all_cases() == []
