from __future__ import annotations

import hashlib
import json
import tempfile
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CaseBlock:
    case_number: str
    title: str | None = None
    sale_date: str | None = None
    status: str | None = None
    is_case_start: bool = True
    y_top: float = 0.0
    y_bottom: float = 1.0
    confidence: float = 0.0


@dataclass
class PageVisionResult:
    case_blocks: list[CaseBlock] = field(default_factory=list)
    review_required: bool = False
    source: str = ""


class VisionProvider(ABC):
    provider_name: str = "vision"

    @property
    @abstractmethod
    def enabled(self) -> bool:
        raise NotImplementedError

    @property
    @abstractmethod
    def model_name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def analyze_page(self, image_path: Path, page_no: int, work_dir: Path) -> PageVisionResult | None:
        raise NotImplementedError


class VisionCache:
    def __init__(self, state_dir: Path | str):
        self.path = Path(state_dir) / "vision_cache.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def save(self) -> None:
        fd, tmp_name = tempfile.mkstemp(dir=str(self.path.parent), prefix=".vision_", suffix=".tmp")
        with open(fd, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2, sort_keys=True)
        Path(tmp_name).replace(self.path)

    @staticmethod
    def hash_file(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                h.update(chunk)
        return h.hexdigest()

    @classmethod
    def build_key(
        cls,
        pdf_hash: str,
        page_no: int,
        image_hash: str,
        provider_name: str,
        model_name: str,
    ) -> str:
        return f"{pdf_hash}:{page_no}:{image_hash}:{provider_name}:{model_name}"

    def get(self, key: str) -> PageVisionResult | None:
        raw = self._data.get(key)
        if not isinstance(raw, dict):
            return None
        blocks_raw = raw.get("case_blocks") if isinstance(raw.get("case_blocks"), list) else []
        blocks: list[CaseBlock] = []
        for item in blocks_raw:
            if not isinstance(item, dict):
                continue
            try:
                blocks.append(CaseBlock(**item))
            except TypeError:
                continue
        return PageVisionResult(
            case_blocks=blocks,
            review_required=bool(raw.get("review_required", False)),
            source=str(raw.get("source", "cache")),
        )

    def set(self, key: str, value: PageVisionResult) -> None:
        self._data[key] = {
            "case_blocks": [asdict(block) for block in value.case_blocks],
            "review_required": value.review_required,
            "source": value.source,
        }
