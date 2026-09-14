from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True, slots=True)
class SynchronizedFrame:
    acquisition_time_ns: int
    images: dict[str, np.ndarray]
    state: np.ndarray
    action: np.ndarray
    diagnostics: dict[str, Any]


class CaptureBackend(ABC):
    """Hardware boundary; ROS-specific code must remain behind this interface."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def frames(self) -> AsyncIterator[SynchronizedFrame]: ...

    def health(self) -> dict:
        return {"ready": True, "missing": [], "rates_hz": {}, "drop_counts": {}}

    def reset_capture_queue(self) -> None:
        """Discard synchronized frames received before a new attempt starts."""
        return None

    async def start(self) -> None:
        """Connect subscriptions before the operator attempts to record."""
        return None

    @abstractmethod
    async def close(self) -> None: ...
