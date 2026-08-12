"""Telegram ingest 중복 처리 정책 검증.

정책:
- 같은 PDF hash라도 새 Telegram 메시지(message_id)면 재처리한다.
- 중복 차단은 같은 update_id 또는 같은 (chat_id, message_id)에만 적용한다.
- legacy processed_pdf_hashes 값은 재처리 차단 gate가 아니다.
"""
from pathlib import Path

import husik.telegram.ingest as ingest_module
from husik.config import Config
from husik.state.store import StateStore
from husik.telegram.ingest import IngestStats, PdfRunResult
from husik.vision.base import CaseBlock


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


def test_same_update_id_is_skipped_even_when_replayed(tmp_path, monkeypatch):
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

    assert calls["count"] == 1
    assert any(ingest_module.DUPLICATE_MSG == text for _, text in telegram.sent_messages)


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


def test_process_pdf_and_send_sets_gemini_stats_and_openai_calls_default_zero(tmp_path, monkeypatch):
    config = _make_config(tmp_path)
    config.gemini_api_key = "gemini-key"
    config.openai_api_key = "openai-key"
    config.openai_vision_enabled = False
    state = StateStore(config.state_dir)

    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    analysis = ingest_module.PageAnalysis(
        page_no=1,
        case_numbers=[],
        page_case_numbers=[],
        rating="등급확인",
        title_candidates=[],
        raw_text="텍스트 있음",
        image_path=tmp_path / "page.jpg",
        source="gemini",
        vision_blocks=[CaseBlock(case_number="2025타경1111", confidence=0.9)],
    )

    monkeypatch.setattr(
        ingest_module,
        "analyze_pdf",
        lambda *_args, **_kwargs: ingest_module.AnalyzedPdf(records=[], analyses=[analysis]),
    )
    monkeypatch.setattr(ingest_module, "get_ocr_runtime_stats", lambda: {"openai_vision_calls": 0})

    stats = IngestStats()
    result = ingest_module.process_pdf_and_send(pdf_path, config, state, config.tmp_dir, stats)

    assert result.detected_cases == 0
    assert stats.vision_provider == "gemini"
    assert stats.gemini_available == "true"
    assert stats.gemini_pages_analyzed == 1
    assert stats.gemini_case_blocks == 1
    assert stats.gemini_cache_hits == 0
    assert stats.gemini_cache_misses == 1
    assert stats.openai_vision_calls == 0
