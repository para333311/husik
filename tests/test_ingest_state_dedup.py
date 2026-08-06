"""필수 수정 6: 성공 기준(사건번호 기준 전송 성공)에 따른 processed hash 저장 정책 검증."""
from pathlib import Path

import husik.telegram.ingest as ingest_module
from husik.config import Config
from husik.state.store import StateStore
from husik.telegram.ingest import PdfRunResult


class FakeTelegram:
    def __init__(self):
        self.sent_messages: list[tuple] = []
        self._next_file_id = 1

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


def _make_update(update_id: int) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "chat": {"id": 999, "type": "private"},
            "from": {"id": 111},
            "document": {"file_id": f"file-{update_id}", "mime_type": "application/pdf", "file_size": 100},
        },
    }


def test_no_case_number_result_does_not_mark_pdf_processed(tmp_path, monkeypatch):
    config = _make_config(tmp_path)
    state = StateStore(config.state_dir)
    telegram = FakeTelegram()

    monkeypatch.setattr(
        ingest_module, "process_pdf_and_send", lambda *a, **k: PdfRunResult(detected_cases=0)
    )

    ingest_module._handle_update(
        _make_update(1), config, state, telegram, config.tmp_dir, ingest_module.IngestStats()
    )

    assert state.telegram_offset == 0  # _handle_update 자체는 offset을 건드리지 않음(poll_and_ingest 책임)
    # 사건번호를 못 찾았으므로 어떤 해시도 processed로 저장되지 않아야 한다.
    assert state._data["processed_pdf_hashes"] == {}
    assert any("사건번호를 찾지 못했습니다" in text for _, text in telegram.sent_messages)


def test_channel_send_failure_does_not_mark_pdf_processed(tmp_path, monkeypatch):
    config = _make_config(tmp_path)
    state = StateStore(config.state_dir)
    telegram = FakeTelegram()

    monkeypatch.setattr(
        ingest_module,
        "process_pdf_and_send",
        lambda *a, **k: PdfRunResult(detected_cases=1, channel_send_failed=True),
    )

    ingest_module._handle_update(
        _make_update(2), config, state, telegram, config.tmp_dir, ingest_module.IngestStats()
    )

    assert state._data["processed_pdf_hashes"] == {}
    assert any(ingest_module.CHANNEL_FAIL_MSG == text for _, text in telegram.sent_messages)


def test_successful_send_marks_pdf_processed(tmp_path, monkeypatch):
    config = _make_config(tmp_path)
    state = StateStore(config.state_dir)
    telegram = FakeTelegram()

    monkeypatch.setattr(
        ingest_module,
        "process_pdf_and_send",
        lambda *a, **k: PdfRunResult(detected_cases=1, cases_sent=1, images_sent=3, notion_upserted=0),
    )

    ingest_module._handle_update(
        _make_update(3), config, state, telegram, config.tmp_dir, ingest_module.IngestStats()
    )

    assert len(state._data["processed_pdf_hashes"]) == 1
    assert any("처리 완료" in text for _, text in telegram.sent_messages)
