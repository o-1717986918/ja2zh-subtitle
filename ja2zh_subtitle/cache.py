from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .models import SubtitleCue


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def file_fingerprint(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


class StageCache:
    def __init__(self, root: Path, enabled: bool = True) -> None:
        self.root = root
        self.enabled = enabled
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, stage: str) -> Path:
        return self.root / f"{stage}.json"

    def load(self, stage: str, signature: str) -> list[SubtitleCue] | None:
        if not self.enabled:
            return None
        path = self._path(stage)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("signature") != signature:
                return None
            return [SubtitleCue.from_dict(item) for item in payload["cues"]]
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def save(self, stage: str, signature: str, cues: list[SubtitleCue]) -> Path:
        path = self._path(stage)
        payload = {
            "signature": signature,
            "cues": [cue.to_dict() for cue in cues],
        }
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)
        return path
