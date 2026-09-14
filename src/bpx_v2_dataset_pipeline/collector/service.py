from __future__ import annotations

import asyncio
import pathlib
from dataclasses import dataclass

from bpx_v2_dataset_pipeline.collector.backend import CaptureBackend
from bpx_v2_dataset_pipeline.collector.episode_writer import EpisodeWriter
from bpx_v2_dataset_pipeline.models import AttemptMetadata, AttemptStatus
from bpx_v2_dataset_pipeline.session_store import SessionStore


@dataclass(slots=True)
class ActiveAttempt:
    attempt_id: int
    metadata: AttemptMetadata
    frame_count: int = 0


class CollectorService:
    """Serializes UI commands and owns exactly one active capture attempt."""

    def __init__(
        self, store: SessionStore, backend: CaptureBackend, recordings_dir: pathlib.Path, writer: EpisodeWriter
    ) -> None:
        self.store = store
        self.backend = backend
        self.recordings_dir = recordings_dir
        self.writer = writer
        self.active: ActiveAttempt | None = None
        self._capture_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._capture_error = ""

    async def start(self, metadata: AttemptMetadata) -> ActiveAttempt:
        async with self._lock:
            if self.active is not None:
                raise RuntimeError("An attempt is already recording")
            health = self.backend.health()
            if self.backend.name != "mock" and not health.get("ready", False):
                missing = ", ".join([*health.get("missing", []), *health.get("stale", [])])
                raise RuntimeError(
                    f"ROS2 inputs are not ready: {missing or 'backend has not received synchronized data'}"
                )
            attempt_id = self.store.begin_attempt(metadata)
            try:
                self._capture_error = ""
                await asyncio.to_thread(self.writer.begin, attempt_id, metadata)
                self.backend.reset_capture_queue()
                self.active = ActiveAttempt(attempt_id=attempt_id, metadata=metadata)
                self._capture_task = asyncio.create_task(self._consume_frames(attempt_id))
            except Exception:
                self.store.finish_attempt(attempt_id, AttemptStatus.INTERRUPTED, note="writer/backend start failed")
                raise
            return self.active

    async def _consume_frames(self, attempt_id: int) -> None:
        try:
            async for frame in self.backend.frames():
                if self.active is None or self.active.attempt_id != attempt_id:
                    return
                self.writer.add_frame(frame)
                self.active.frame_count += 1
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._capture_error = f"{type(error).__name__}: {error}"

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
            if status == AttemptStatus.SUCCESS and self._capture_error:
                await asyncio.to_thread(self.writer.discard)
                self.store.finish_attempt(
                    active.attempt_id,
                    AttemptStatus.INTERRUPTED,
                    note=f"capture failed: {self._capture_error}",
                )
                raise RuntimeError(f"capture failed; episode was discarded: {self._capture_error}")
            artifact_path = ""
            try:
                if status == AttemptStatus.SUCCESS:
                    artifact_path = await asyncio.to_thread(self.writer.commit)
                else:
                    await asyncio.to_thread(self.writer.discard)
            except Exception as error:
                self.store.finish_attempt(
                    active.attempt_id,
                    AttemptStatus.INTERRUPTED,
                    note=f"episode finalization failed: {type(error).__name__}: {error}",
                )
                raise RuntimeError(f"episode finalization failed: {error}") from error
            self.store.finish_attempt(
                active.attempt_id,
                status,
                failure_reason=failure_reason,
                note=note or active.metadata.note,
                artifact_path=artifact_path,
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
            "capture_health": self.backend.health(),
            "writer": self.writer.status(),
            "capture_error": self._capture_error,
        }

    async def close(self) -> None:
        if self.active is not None:
            await self.finish(AttemptStatus.INTERRUPTED, note="collector service stopped")
        await self.backend.close()
        await asyncio.to_thread(self.writer.close)
