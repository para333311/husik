from pathlib import Path

from PIL import Image

from husik.pdf.detect_cases import CaseRecord
from husik.pdf.segment import ImageSegment
from husik.telegram.client import TelegramError
from husik.telegram.ingest import _send_image_chunk, send_case_to_telegram, send_photo_with_fallback


def _make_image(path: Path, size=(100, 100)) -> Path:
    Image.new("RGB", size, color="white").save(path, "JPEG")
    return path


class FakeTelegramClient:
    def __init__(self):
        self.send_photo_calls = []
        self.send_media_group_calls = []
        self.send_message_calls = []
        self.media_group_should_fail = True
        self.next_id = 1

    def _next(self) -> int:
        msg_id = self.next_id
        self.next_id += 1
        return msg_id

    def send_message(self, chat_id, text, reply_to_message_id=None, parse_mode=None):
        self.send_message_calls.append((chat_id, text, parse_mode))
        return {"message_id": self._next()}

    def send_media_group(self, chat_id, photo_paths, captions=None, reply_to_message_id=None):
        self.send_media_group_calls.append((chat_id, list(photo_paths), reply_to_message_id))
        if self.media_group_should_fail:
            raise TelegramError("media group blocked")
        return [{"message_id": self._next()} for _ in photo_paths]

    def send_photo(self, chat_id, photo_path, caption="", reply_to_message_id=None):
        self.send_photo_calls.append((chat_id, photo_path, reply_to_message_id))
        return {"message_id": self._next()}


def test_send_media_group_failure_falls_back_to_send_photo_per_image(tmp_path):
    client = FakeTelegramClient()
    paths = [_make_image(tmp_path / f"p{i}.jpg") for i in range(3)]
    captions = [f"{i}p" for i in range(3)]

    ids, failed = _send_image_chunk(client, "-100123", paths, captions, reply_to_message_id=999)

    assert failed == 0
    assert len(ids) == 3
    # sendMediaGroup was attempted (with and without reply) before falling back
    assert len(client.send_media_group_calls) == 2
    assert len(client.send_photo_calls) == 3


def test_send_media_group_success_does_not_use_fallback(tmp_path):
    client = FakeTelegramClient()
    client.media_group_should_fail = False
    paths = [_make_image(tmp_path / f"p{i}.jpg") for i in range(2)]
    captions = ["1p", "2p"]

    ids, failed = _send_image_chunk(client, "-100123", paths, captions, reply_to_message_id=1)

    assert failed == 0
    assert len(ids) == 2
    assert len(client.send_media_group_calls) == 1
    assert len(client.send_photo_calls) == 0


class AlwaysFailingPhotoClient:
    def send_photo(self, chat_id, photo_path, caption="", reply_to_message_id=None):
        raise TelegramError("photo rejected")


def test_send_photo_with_fallback_returns_none_when_everything_fails(tmp_path):
    client = AlwaysFailingPhotoClient()
    path = _make_image(tmp_path / "big.jpg", size=(50, 50))

    result = send_photo_with_fallback(client, "-100123", path, "1p", reply_to_message_id=None)

    assert result is None


def _build_record_with_images(tmp_path, image_count: int) -> CaseRecord:
    segments = []
    for i in range(image_count):
        path = _make_image(tmp_path / f"p{i + 1}.jpg")
        segments.append(ImageSegment(case_number="2025타경102095", page_no=i + 1, image_path=path))
    return CaseRecord(
        case_number="2025타경102095",
        rating="$$$",
        title="사당 15 추천 $$$",
        page_start=1,
        page_end=max(1, image_count),
        image_segments=segments,
    )


def test_send_case_to_telegram_uses_html_parse_mode(tmp_path):
    client = FakeTelegramClient()
    client.media_group_should_fail = False
    record = _build_record_with_images(tmp_path, 1)

    send_case_to_telegram(client, "-100123", record, "<b>본문</b>")

    assert len(client.send_message_calls) == 1
    _, _, parse_mode = client.send_message_calls[0]
    assert parse_mode == "HTML"


def test_no_continue_message_when_images_not_exceed_10(tmp_path):
    client = FakeTelegramClient()
    client.media_group_should_fail = False
    record = _build_record_with_images(tmp_path, 10)

    send_case_to_telegram(client, "-100123", record, "대표")

    texts = [call[1] for call in client.send_message_calls]
    assert texts == ["대표"]


def test_continue_message_created_when_images_exceed_10(tmp_path):
    client = FakeTelegramClient()
    client.media_group_should_fail = False
    record = _build_record_with_images(tmp_path, 11)

    send_case_to_telegram(client, "-100123", record, "대표")

    texts = [call[1] for call in client.send_message_calls]
    assert texts == ["대표", "[2025타경102095-계속]"]


def test_multiple_continue_messages_for_21_plus_images(tmp_path):
    client = FakeTelegramClient()
    client.media_group_should_fail = False
    record = _build_record_with_images(tmp_path, 21)

    send_case_to_telegram(client, "-100123", record, "대표")

    texts = [call[1] for call in client.send_message_calls]
    assert texts == ["대표", "[2025타경102095-계속]", "[2025타경102095-계속 2]"]
