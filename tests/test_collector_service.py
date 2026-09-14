import asyncio
from collections.abc import AsyncIterator

import pytest

from bpx_v2_dataset_pipeline.collector.backend import CaptureBackend, SynchronizedFrame
from bpx_v2_dataset_pipeline.collector.episode_writer import EpisodeWriter, LeRobotV21EpisodeWriter
from bpx_v2_dataset_pipeline.collector.service import CollectorService
from bpx_v2_dataset_pipeline.models import AttemptMetadata, AttemptStatus
from bpx_v2_dataset_pipeline.session_store import SessionStore


class IdleBackend(CaptureBackend):
    def __init__(self, ready: bool = True) -> None:
        self.ready = ready

    @property
    def name(self) -> str:
        return "test"

    def health(self) -> dict:
        return {"ready": self.ready, "missing": [] if self.ready else ["left_eye"], "stale": []}

    async def frames(self) -> AsyncIterator[SynchronizedFrame]:
        while True:
            await asyncio.sleep(10)
            if False:
                yield

    async def close(self) -> None:
        pass


class RecordingWriter(EpisodeWriter):
    def __init__(self) -> None:
        self.events = []

    def begin(self, attempt_id: int, metadata: AttemptMetadata) -> None:
        self.events.append(("begin", attempt_id))

    def add_frame(self, frame: SynchronizedFrame) -> None:
        self.events.append(("frame", frame))

    def commit(self) -> str:
        self.events.append(("commit",))
        return "data/chunk-000/episode_000000.parquet"

    def discard(self) -> None:
        self.events.append(("discard",))


def metadata() -> AttemptMetadata:
    return AttemptMetadata(
        session_id="session",
        task_en="Pick up the red block.",
        operator_id="operator_01",
        layout_id="layout_01",
        embodiment="gripper",
    )


def test_success_commits_and_failure_discards(tmp_path) -> None:
    async def scenario() -> None:
        store = SessionStore(tmp_path / "collector.sqlite3")
        writer = RecordingWriter()
        service = CollectorService(store, IdleBackend(), tmp_path / "dataset", writer)

        first = await service.start(metadata())
        result = await service.finish(AttemptStatus.SUCCESS)
        assert result["artifact_path"].endswith("episode_000000.parquet")
        assert writer.events[:2] == [("begin", first.attempt_id), ("commit",)]

        await service.start(metadata())
        await service.finish(AttemptStatus.FAILURE)
        assert writer.events[-1] == ("discard",)

    asyncio.run(scenario())


def test_not_ready_backend_cannot_allocate_attempt(tmp_path) -> None:
    async def scenario() -> None:
        store = SessionStore(tmp_path / "collector.sqlite3")
        service = CollectorService(store, IdleBackend(False), tmp_path / "dataset", RecordingWriter())
        with pytest.raises(RuntimeError, match="left_eye"):
            await service.start(metadata())
        assert store.recent_attempts() == []

    asyncio.run(scenario())


def test_lerobot_schema_has_four_videos_18d_vectors_and_audit_timestamps() -> None:
    features = LeRobotV21EpisodeWriter.features()
    assert {name for name, spec in features.items() if spec["dtype"] == "video"} == {
        "observation.images.left_eye",
        "observation.images.right_eye",
        "observation.images.left_wrist",
        "observation.images.right_wrist",
    }
    assert features["observation.state"]["shape"] == (18,)
    assert features["action"]["shape"] == (18,)
    assert features["bpx.receive_time_ns"]["shape"] == (10,)


def test_lerobot_writer_recovers_an_uninitialized_episode_buffer(tmp_path) -> None:
    class Dataset:
        episode_buffer = None

        def create_episode_buffer(self):
            return {"episode_index": 4}

        def _wait_image_writer(self):
            self.waited = True

        def clear_episode_buffer(self):
            self.cleared = True

    dataset = Dataset()
    writer = LeRobotV21EpisodeWriter(tmp_path / "dataset")
    writer._load = lambda: dataset
    writer.begin(9, metadata())
    assert dataset.waited is True
    assert dataset.cleared is True
