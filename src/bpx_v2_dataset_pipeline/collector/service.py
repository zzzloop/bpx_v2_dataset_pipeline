from __future__ import annotations

import asyncio
import pathlib
from dataclasses import dataclass

from bpx_v2_dataset_pipeline.collector.backend import CaptureBackend
from bpx_v2_dataset_pipeline.models import AttemptMetadata, AttemptStatus
from bpx_v2_dataset_pipeline.session_store import SessionStore


@dataclass(slots=True)
class ActiveAttempt:
    attempt_id: int
    metadata: AttemptMetadata
    frame_count: int = 0


class CollectorService:
    """Serializes UI commands and owns exactly one active capture attempt."""

    def __init__(self, store: SessionStore, backend: CaptureBackend, recordings_dir: pathlib.Path) -> None:
        self.store = store
        self.backend = backend
        self.recordings_dir = recordings_dir
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        self.active: ActiveAttempt | None = None
        self._capture_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def start(self, metadata: AttemptMetadata) -> ActiveAttempt:
        async with self._lock:
            if self.active is not None:
                raise RuntimeError("An attempt is already recording")
            attempt_id = self.store.begin_attempt(metadata)
            self.active = ActiveAttempt(attempt_id=attempt_id, metadata=metadata)
            self._capture_task = asyncio.create_task(self._consume_frames(attempt_id))
            return self.active

    async def _consume_frames(self, attempt_id: int) -> None:
        async for _frame in self.backend.frames():
            if self.active is None or self.active.attempt_id != attempt_id:
                return
            # Mock mode validates timing and lifecycle only. The production
            # LeRobot shard writer is enabled with the future ROS2 schema.
            self.active.frame_count += 1

    async def finish(
        self,
        status: AttemptStatus,
        *,
        failure_reason: str = "",
        note: str = "",
    ) -> dict:
        async with self._lock:
            if self.active is None:
                raise RuntimeError("No attempt is recording")
            active = self.active
            self.active = None
            if self._capture_task is not None:
                self._capture_task.cancel()
                await asyncio.gather(self._capture_task, return_exceptions=True)
                self._capture_task = None
            self.store.finish_attempt(
                active.attempt_id,
                status,
                failure_reason=failure_reason,
                note=note or active.metadata.note,
            )
            return self.store.get_attempt(active.attempt_id) | {"frame_count": active.frame_count}

    def status(self) -> dict:
        active = self.active
        return {
            "backend": self.backend.name,
            "mode": "recording" if active else "idle",
            "active_attempt": None
            if active is None
            else {"attempt_id": active.attempt_id, "frame_count": active.frame_count},
            "recent_attempts": self.store.recent_attempts(20),
        }
