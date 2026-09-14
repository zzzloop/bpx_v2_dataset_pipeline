from __future__ import annotations

import json
import pathlib
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import ClassVar

import numpy as np

from bpx_v2_dataset_pipeline.collector.backend import SynchronizedFrame
from bpx_v2_dataset_pipeline.models import AttemptMetadata


class EpisodeWriter(ABC):
    @abstractmethod
    def begin(self, attempt_id: int, metadata: AttemptMetadata) -> None: ...

    @abstractmethod
    def add_frame(self, frame: SynchronizedFrame) -> None: ...

    @abstractmethod
    def commit(self) -> str: ...

    @abstractmethod
    def discard(self) -> None: ...

    def status(self) -> dict:
        return {"format": "none", "ready": True}

    def close(self) -> None:
        return None


class NullEpisodeWriter(EpisodeWriter):
    def begin(self, attempt_id: int, metadata: AttemptMetadata) -> None:
        pass

    def add_frame(self, frame: SynchronizedFrame) -> None:
        pass

    def commit(self) -> str:
        return ""

    def discard(self) -> None:
        pass

    def status(self) -> dict:
        return {"format": "mock/no-output", "ready": True}


class LeRobotV21EpisodeWriter(EpisodeWriter):
    """Append successful attempts to one local LeRobot v2.1 MP4 dataset."""

    REPO_ID = "bpx/bpx_v2_humanoid_raw"
    JOINT_NAMES: ClassVar[list[str]] = [
        *(f"left_arm_{index}" for index in range(7)),
        *(f"right_arm_{index}" for index in range(7)),
        "head_pan",
        "head_tilt",
        "left_gripper",
        "right_gripper",
    ]
    STREAM_NAMES: ClassVar[list[str]] = [
        "left_eye",
        "right_eye",
        "left_wrist",
        "right_wrist",
        "arm_state",
        "head_state",
        "gripper_state",
        "arm_action",
        "head_action",
        "gripper_action",
    ]

    def __init__(self, root: pathlib.Path, *, fps: int = 30, image_writer_threads: int = 16) -> None:
        self.root = root.resolve()
        self.fps = fps
        self.image_writer_threads = image_writer_threads
        self._dataset = None
        self._attempt_id: int | None = None
        self._metadata: AttemptMetadata | None = None
        self._frame_count = 0

    @staticmethod
    def features() -> dict:
        image = {"dtype": "video", "shape": (480, 640, 3), "names": ["height", "width", "channel"]}
        return {
            **{
                f"observation.images.{name}": dict(image)
                for name in ("left_eye", "right_eye", "left_wrist", "right_wrist")
            },
            "observation.state": {
                "dtype": "float32",
                "shape": (18,),
                "names": list(LeRobotV21EpisodeWriter.JOINT_NAMES),
            },
            "action": {"dtype": "float32", "shape": (18,), "names": list(LeRobotV21EpisodeWriter.JOINT_NAMES)},
            "bpx.receive_time_ns": {
                "dtype": "int64",
                "shape": (10,),
                "names": list(LeRobotV21EpisodeWriter.STREAM_NAMES),
            },
            "bpx.source_time_ns": {
                "dtype": "int64",
                "shape": (10,),
                "names": list(LeRobotV21EpisodeWriter.STREAM_NAMES),
            },
            "bpx.gripper_raw": {
                "dtype": "float32",
                "shape": (4,),
                "names": ["state_left", "state_right", "action_left", "action_right"],
            },
        }

    def _load(self):
        if self._dataset is not None:
            return self._dataset
        try:
            from lerobot.common.datasets.lerobot_dataset import CODEBASE_VERSION, LeRobotDataset
        except ImportError as error:
            raise RuntimeError(
                "LeRobot is not installed in the ROS2 environment. Install the project-pinned LeRobot v2.1 "
                "once while online; recording startup never downloads packages."
            ) from error
        if CODEBASE_VERSION != "v2.1":
            raise RuntimeError(f"collector requires LeRobot v2.1, found {CODEBASE_VERSION!r}")

        info_path = self.root / "meta" / "info.json"
        if info_path.is_file():
            dataset = LeRobotDataset(self.REPO_ID, root=self.root, download_videos=False)
            if dataset.image_writer is None:
                dataset.start_image_writer(num_processes=0, num_threads=self.image_writer_threads)
        else:
            if self.root.exists() and any(self.root.iterdir()):
                raise RuntimeError(f"refusing non-empty non-LeRobot output directory: {self.root}")
            if self.root.exists():
                self.root.rmdir()
            dataset = LeRobotDataset.create(
                repo_id=self.REPO_ID,
                root=self.root,
                robot_type="bpx_v2_gripper",
                fps=self.fps,
                features=self.features(),
                use_videos=True,
                image_writer_threads=self.image_writer_threads,
                image_writer_processes=0,
            )
        self._dataset = dataset
        return dataset

    def begin(self, attempt_id: int, metadata: AttemptMetadata) -> None:
        if self._attempt_id is not None:
            raise RuntimeError("writer already has an active attempt")
        if metadata.embodiment.value != "gripper":
            raise RuntimeError(
                "this schema records the dual gripper only; dexterous-hand capture needs a separate dataset"
            )
        dataset = self._load()
        if dataset.episode_buffer is None:
            dataset.episode_buffer = dataset.create_episode_buffer()
        dataset._wait_image_writer()
        dataset.clear_episode_buffer()
        self._attempt_id = attempt_id
        self._metadata = metadata
        self._frame_count = 0

    def add_frame(self, frame: SynchronizedFrame) -> None:
        if self._attempt_id is None or self._metadata is None:
            raise RuntimeError("writer has no active attempt")
        if frame.state.shape != (18,) or frame.action.shape != (18,):
            raise ValueError(f"expected 18D state/action, got {frame.state.shape}/{frame.action.shape}")
        receive_times = frame.diagnostics["receive_time_ns"]
        source_times = frame.diagnostics["source_time_ns"]
        self._dataset.add_frame(
            {
                **{
                    f"observation.images.{name}": frame.images[name]
                    for name in ("left_eye", "right_eye", "left_wrist", "right_wrist")
                },
                "observation.state": frame.state,
                "action": frame.action,
                "bpx.receive_time_ns": np.asarray(
                    [int(receive_times[name]) for name in self.STREAM_NAMES], dtype=np.int64
                ),
                "bpx.source_time_ns": np.asarray(
                    [int(source_times[name] or -1) for name in self.STREAM_NAMES], dtype=np.int64
                ),
                "bpx.gripper_raw": np.asarray(
                    [*frame.diagnostics["gripper_state_raw"], *frame.diagnostics["gripper_action_raw"]],
                    dtype=np.float32,
                ),
                "task": self._metadata.task_en,
            }
        )
        self._frame_count += 1

    def commit(self) -> str:
        if self._attempt_id is None or self._metadata is None:
            raise RuntimeError("writer has no active attempt")
        if self._frame_count == 0:
            raise RuntimeError("cannot save an empty episode")
        episode_index = int(self._dataset.meta.total_episodes)
        self._dataset.save_episode()
        self._append_attempt_metadata(episode_index)
        artifact = str(self.root / self._dataset.meta.get_data_file_path(episode_index))
        self._reset_active()
        return artifact

    def discard(self) -> None:
        if self._attempt_id is None:
            return
        self._dataset._wait_image_writer()
        self._dataset.clear_episode_buffer()
        self._reset_active()

    def _append_attempt_metadata(self, episode_index: int) -> None:
        path = self.root / "meta" / "bpx_attempts.jsonl"
        record = {
            "episode_index": episode_index,
            "attempt_id": self._attempt_id,
            "session_id": self._metadata.session_id,
            "task_en": self._metadata.task_en,
            "task_zh": self._metadata.task_zh,
            "operator_id": self._metadata.operator_id,
            "layout_id": self._metadata.layout_id,
            "embodiment": self._metadata.embodiment.value,
            "note": self._metadata.note,
            "frames": self._frame_count,
            "saved_at": datetime.now(UTC).isoformat(),
        }
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _reset_active(self) -> None:
        self._attempt_id = None
        self._metadata = None
        self._frame_count = 0

    def status(self) -> dict:
        return {
            "format": "LeRobot v2.1 / MP4",
            "ready": True,
            "root": str(self.root),
            "repo_id": self.REPO_ID,
            "active_frames": self._frame_count,
        }

    def close(self) -> None:
        if self._dataset is not None:
            if self._attempt_id is not None:
                self.discard()
            self._dataset.stop_image_writer()
