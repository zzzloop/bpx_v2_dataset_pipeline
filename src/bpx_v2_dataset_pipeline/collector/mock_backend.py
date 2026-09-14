from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

import numpy as np

from bpx_v2_dataset_pipeline.collector.backend import CaptureBackend, SynchronizedFrame


class MockCaptureBackend(CaptureBackend):
    """UI/state-machine test backend. It never communicates with robot hardware."""

    def __init__(self, fps: float = 30.0) -> None:
        if fps <= 0:
            raise ValueError("fps must be positive")
        self._period = 1.0 / fps
        self._closed = False
        self._index = 0

    @property
    def name(self) -> str:
        return "mock"

    async def frames(self) -> AsyncIterator[SynchronizedFrame]:
        while not self._closed:
            await asyncio.sleep(self._period)
            value = self._index % 256
            image = np.full((48, 64, 3), value, dtype=np.uint8)
            yield SynchronizedFrame(
                acquisition_time_ns=time.monotonic_ns(),
                images={name: image.copy() for name in ("left_eye", "right_eye", "left_wrist", "right_wrist")},
                state=np.zeros(1, dtype=np.float32),
                action=np.zeros(1, dtype=np.float32),
                diagnostics={"mock": True},
            )
            self._index += 1

    async def close(self) -> None:
        self._closed = True
