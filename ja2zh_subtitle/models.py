from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class WordTiming:
    start: float
    end: float
    text: str
    probability: float | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "WordTiming":
        return cls(
            start=float(value["start"]),
            end=float(value["end"]),
            text=str(value["text"]),
            probability=(
                float(value["probability"])
                if value.get("probability") is not None
                else None
            ),
        )


@dataclass(slots=True)
class SubtitleCue:
    id: int
    start: float
    end: float
    ja: str
    raw_zh: str = ""
    zh: str = ""
    confidence: float | None = None
    words: list[WordTiming] = field(default_factory=list)
    origin: str = "primary"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SubtitleCue":
        return cls(
            id=int(value["id"]),
            start=float(value["start"]),
            end=float(value["end"]),
            ja=str(value.get("ja", "")),
            raw_zh=str(value.get("raw_zh", "")),
            zh=str(value.get("zh", "")),
            confidence=(
                float(value["confidence"])
                if value.get("confidence") is not None
                else None
            ),
            words=[WordTiming.from_dict(item) for item in value.get("words", [])],
            origin=str(value.get("origin", "primary")),
        )


@dataclass(slots=True)
class DeviceProfile:
    torch_available: bool
    cuda_available: bool
    device: str
    vram_gb: float | None
    ram_gb: float | None
    recommended_preset: str
    notes: list[str] = field(default_factory=list)
