from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class SynchronizedFrame:
    acquisition_time_ns: int
    images: dict[str, np.ndarray]
    state: np.ndarray
    action: np.ndarray


class CaptureBackend(ABC):
    """Hardware boundary; ROS-specific code must remain behind this interface."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def frames(self) -> AsyncIterator[SynchronizedFrame]: ...

    @abstractmethod
    async def close(self) -> None: ...
