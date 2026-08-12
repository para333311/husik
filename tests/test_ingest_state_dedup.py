"""Telegram ingest 중복 처리 정책 검증.

정책:
- 같은 PDF hash라도 새 Telegram 메시지(message_id)면 재처리한다.
- 중복 차단은 같은 (chat_id, message_id)에만 적용한다.
- legacy processed_pdf_hashes 값은 재처리 차단 gate가 아니다.
"""
from pathlib import Path

import husik.telegram.ingest as ingest_module
from husik.config import Config
from husik.state.store import StateStore
from husik.telegram.ingest import IngestStats, PdfRunResult


class FakeTelegram:
    def __init__(self):
        self.sent_messages: list[tuple] = []

    def get_file(self, file_id):
        return {"file_path": "dummy/path.pdf"}

    def download_file(self, file_path, dest: Path):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"%PDF-1.4 fake content")
        return dest

    def send_message(self, chat_id, text, reply_to_message_id=None):
        self.sent_messages.append((chat_id, text))
        return {"message_id": len(self.sent_messages)}


def _make_config(tmp_path) -> Config:
    return Config(
        telegram_auction_bot_token="fake-token",
        telegram_audio_bot_token="",
        telegram_auction_channel_id="-1001234567890",
        telegram_audio_channel_id="",
        telegram_allowed_user_id="111",
        openai_api_key="",
        notion_token="",
        notion_auction_db_url="",
        naver_client_id="",
        naver_client_secret="",
        court_auction_enabled=False,
        madangs_enabled=False,
        blog_monitor_enabled=False,
        state_dir=tmp_path / "state",
        tmp_dir=tmp_path / "tmp",
    )


def _make_update(update_id: int, message_id: int) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": message_id,
            "chat": {"id": 999, "type": "private"},
            "from": {"id": 111},
            "document": {"file_id": f"file-{update_id}", "mime_type": "application/pdf", "file_size": 100},
        },
    }


def _success_result() -> PdfRunResult:
    return PdfRunResult(detected_cases=1, cases_sent=1, images_sent=3, notion_upserted=0)


def _handle(update: dict, config: Config, state: StateStore, telegram: FakeTelegram) -> None:
    ingest_module._handle_update(update, config, state, telegram, config.tmp_dir, ingest_module.IngestStats())


def test_same_pdf_hash_with_different_message_id_is_reprocessed(tmp_path, monkeypatch):
    config = _make_config(tmp_path)
    state = StateStore(config.state_dir)
    telegram = FakeTelegram()
    calls = {"count": 0}

    def fake_process(*args, **kwargs):
        calls["count"] += 1
        return _success_result()

    monkeypatch.setattr(ingest_module, "hash_file", lambda *_: "same-hash")
    monkeypatch.setattr(ingest_module, "process_pdf_and_send", fake_process)

    _handle(_make_update(update_id=1, message_id=101), config, state, telegram)
    _handle(_make_update(update_id=2, message_id=102), config, state, telegram)

    assert calls["count"] == 2
    assert not any("이미 처리된 메시지입니다." in text for _, text in telegram.sent_messages)
    assert not any("이미 처리된 PDF입니다 (중복)." in text for _, text in telegram.sent_messages)


def test_same_pdf_hash_with_same_message_id_is_skipped(tmp_path, monkeypatch):
    config = _make_config(tmp_path)
    state = StateStore(config.state_dir)
    telegram = FakeTelegram()
    calls = {"count": 0}

    def fake_process(*args, **kwargs):
        calls["count"] += 1
        return _success_result()

    monkeypatch.setattr(ingest_module, "hash_file", lambda *_: "same-hash")
    monkeypatch.setattr(ingest_module, "process_pdf_and_send", fake_process)

    _handle(_make_update(update_id=10, message_id=777), config, state, telegram)
    _handle(_make_update(update_id=11, message_id=777), config, state, telegram)

    assert calls["count"] == 1
    assert any(ingest_module.DUPLICATE_MSG == text for _, text in telegram.sent_messages)


def test_same_update_id_with_different_message_id_is_reprocessed(tmp_path, monkeypatch):
    config = _make_config(tmp_path)
    state = StateStore(config.state_dir)
    telegram = FakeTelegram()
    calls = {"count": 0}

    def fake_process(*args, **kwargs):
        calls["count"] += 1
        return _success_result()

    monkeypatch.setattr(ingest_module, "hash_file", lambda *_: "same-hash")
    monkeypatch.setattr(ingest_module, "process_pdf_and_send", fake_process)

    _handle(_make_update(update_id=33, message_id=901), config, state, telegram)
    _handle(_make_update(update_id=33, message_id=902), config, state, telegram)

    assert calls["count"] == 2
    assert not any(ingest_module.DUPLICATE_MSG == text for _, text in telegram.sent_messages)


def test_legacy_processed_hash_does_not_block_new_upload(tmp_path, monkeypatch):
    config = _make_config(tmp_path)
    state = StateStore(config.state_dir)
    telegram = FakeTelegram()
    calls = {"count": 0}

    state.mark_pdf_processed("same-hash", {"file_name": "legacy.pdf"})

    def fake_process(*args, **kwargs):
        calls["count"] += 1
        return _success_result()

    monkeypatch.setattr(ingest_module, "hash_file", lambda *_: "same-hash")
    monkeypatch.setattr(ingest_module, "process_pdf_and_send", fake_process)

    _handle(_make_update(update_id=55, message_id=1234), config, state, telegram)

    assert calls["count"] == 1
    assert not any("이미 처리된 PDF입니다 (중복)." in text for _, text in telegram.sent_messages)
    assert not any(ingest_module.DUPLICATE_MSG == text for _, text in telegram.sent_messages)


class FakeTelegramPhotoClient:
    def __init__(self):
        self.send_photo_calls: list[Path] = []
        self.send_media_group_calls: int = 0

    def send_photo(self, chat_id, photo_path, caption="", reply_to_message_id=None):
        assert caption == ""
        assert reply_to_message_id is None
        self.send_photo_calls.append(photo_path)
        return {"message_id": len(self.send_photo_calls)}

    def send_media_group(self, *args, **kwargs):
        self.send_media_group_calls += 1
        raise AssertionError("media group must not be called")


def _build_pdf(path: Path, page_count: int) -> None:
    fitz = __import__("fitz")
    doc = fitz.open()
    for i in range(page_count):
        page = doc.new_page(width=595, height=842)
        page.insert_text((50, 120), f"PAGE {i + 1}", fontsize=24)
    doc.save(str(path))
    doc.close()


def test_process_pdf_and_send_simple_bundle_mode_disables_ai_and_external_calls(tmp_path, monkeypatch):
    config = _make_config(tmp_path)
    state = StateStore(config.state_dir)
    pdf_path = tmp_path / "sample9.pdf"
    _build_pdf(pdf_path, 9)

    fake_telegram = FakeTelegramPhotoClient()

    monkeypatch.setattr(ingest_module, "TelegramClient", lambda *_args, **_kwargs: fake_telegram)
    monkeypatch.setattr(
        ingest_module,
        "analyze_pdf",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("analyze_pdf must not be called")),
    )
    monkeypatch.setattr(
        ingest_module,
        "enrich_case",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("enrich_case must not be called")),
    )
    monkeypatch.setattr(
        ingest_module,
        "find_new_posts",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("find_new_posts must not be called")),
    )
    monkeypatch.setattr(
        ingest_module,
        "NotionClient",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("NotionClient must not be called")),
    )

    stats = IngestStats()
    result = ingest_module.process_pdf_and_send(pdf_path, config, state, config.tmp_dir, stats)

    assert result.images_sent == 3
    assert result.images_failed == 0
    sent_names = [p.name for p in fake_telegram.send_photo_calls]
    assert sent_names == ["image_001_004.jpg", "image_005_008.jpg", "image_009_009.jpg"]
    assert fake_telegram.send_media_group_calls == 0

    assert stats.gemini_pages_analyzed == 0
    assert stats.openai_vision_calls == 0
    assert stats.tesseract_calls == 0
    assert stats.notion_upserted == 0
    assert stats.blog_calls == 0


def test_simple_bundle_never_sends_more_than_four_source_pages_per_image(tmp_path, monkeypatch):
    config = _make_config(tmp_path)
    state = StateStore(config.state_dir)
    pdf_path = tmp_path / "sample21.pdf"
    _build_pdf(pdf_path, 21)

    fake_telegram = FakeTelegramPhotoClient()
    monkeypatch.setattr(ingest_module, "TelegramClient", lambda *_args, **_kwargs: fake_telegram)

    stats = IngestStats()
    ingest_module.process_pdf_and_send(pdf_path, config, state, config.tmp_dir, stats)

    sent_names = [p.name for p in fake_telegram.send_photo_calls]
    assert sent_names == [
        "image_001_004.jpg",
        "image_005_008.jpg",
        "image_009_012.jpg",
        "image_013_016.jpg",
        "image_017_020.jpg",
        "image_021_021.jpg",
    ]
