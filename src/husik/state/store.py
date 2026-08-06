"""data/state 아래 JSON으로 처리 상태를 저장하는 StateStore.

원본 PDF/이미지는 여기 저장하지 않는다. Telegram update offset, 처리된 PDF hash,
사건번호별 대표 메시지/이미지 메시지 ID, Notion page ID만 보관한다.
"""
from __future__ import annotations

import json
import logging
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

STATE_FILENAME = "state.json"


@dataclass
class CaseState:
    case_number: str
    channel_id: str = ""
    representative_message_id: int | None = None
    image_message_ids: list[int] = field(default_factory=list)
    notion_page_id: str | None = None
    rating: str | None = None
    title: str = ""
    status: str = "확인중"
    blog_urls: list[str] = field(default_factory=list)
    auction_info: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CaseState:
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


def _empty_state() -> dict[str, Any]:
    return {"telegram_offset": 0, "processed_pdf_hashes": {}, "cases": {}}


class StateStore:
    def __init__(self, state_dir: Path | str):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.state_dir / STATE_FILENAME
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return _empty_state()
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            for key, default in _empty_state().items():
                data.setdefault(key, default)
            return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("failed to load state file %s, starting fresh: %s", self.path, exc)
            return _empty_state()

    def save(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=self.state_dir, prefix=".state_", suffix=".tmp")
        try:
            with open(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2, sort_keys=True)
            Path(tmp_name).replace(self.path)
        except Exception:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    @property
    def telegram_offset(self) -> int:
        return int(self._data.get("telegram_offset", 0))

    @telegram_offset.setter
    def telegram_offset(self, value: int) -> None:
        self._data["telegram_offset"] = value

    def has_processed_pdf(self, pdf_hash: str) -> bool:
        return pdf_hash in self._data.setdefault("processed_pdf_hashes", {})

    def mark_pdf_processed(self, pdf_hash: str, meta: dict[str, Any]) -> None:
        self._data.setdefault("processed_pdf_hashes", {})[pdf_hash] = meta

    def get_case(self, case_number: str) -> CaseState | None:
        raw = self._data.setdefault("cases", {}).get(case_number)
        return CaseState.from_dict(raw) if raw else None

    def upsert_case(self, case: CaseState) -> None:
        self._data.setdefault("cases", {})[case.case_number] = case.to_dict()

    def all_cases(self) -> list[CaseState]:
        return [CaseState.from_dict(v) for v in self._data.get("cases", {}).values()]
