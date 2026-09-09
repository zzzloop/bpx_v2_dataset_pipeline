from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Embodiment(StrEnum):
    GRIPPER = "gripper"
    DEXTEROUS_HAND = "dexterous_hand"


class AttemptStatus(StrEnum):
    RECORDING = "recording"
    SUCCESS = "success"
    FAILURE = "failure"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True, slots=True)
class AttemptMetadata:
    session_id: str
    task_en: str
    operator_id: str
    layout_id: str
    embodiment: Embodiment
    task_zh: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "embodiment", Embodiment(self.embodiment))
        for name in ("session_id", "task_en", "operator_id", "layout_id"):
            value = getattr(self, name).strip()
            if not value:
                raise ValueError(f"{name} cannot be empty")
            object.__setattr__(self, name, value)
        object.__setattr__(self, "task_zh", self.task_zh.strip())
        object.__setattr__(self, "note", self.note.strip())
