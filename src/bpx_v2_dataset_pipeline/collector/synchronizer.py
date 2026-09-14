from __future__ import annotations

import threading
import time
from collections import Counter, deque
from dataclasses import dataclass
from typing import Any

import numpy as np

from bpx_v2_dataset_pipeline.collector.backend import SynchronizedFrame

CAMERAS = ("left_eye", "right_eye", "left_wrist", "right_wrist")
NUMERIC_KEYS = ("arm_state", "head_state", "gripper_state", "arm_action", "head_action", "gripper_action")


@dataclass(frozen=True, slots=True)
class TimedValue:
    receive_time_ns: int
    value: Any
    source_time_ns: int | None = None


class FrameSynchronizer:
    """Build 30 Hz training frames from independently arriving ROS2 streams."""

    def __init__(
        self,
        *,
        image_tolerance_ms: float = 20.0,
        joint_max_age_ms: float = 50.0,
        gripper_max_age_ms: float = 250.0,
        buffer_size: int = 64,
    ) -> None:
        self.image_tolerance_ns = int(image_tolerance_ms * 1e6)
        self.joint_max_age_ns = int(joint_max_age_ms * 1e6)
        self.gripper_max_age_ns = int(gripper_max_age_ms * 1e6)
        self._buffers = {key: deque(maxlen=buffer_size) for key in (*CAMERAS, *NUMERIC_KEYS)}
        self._last_anchor_ns = -1
        self._lock = threading.Lock()
        self._counts: Counter[str] = Counter()
        self._first_receive_ns: dict[str, int] = {}
        self._last_receive_ns: dict[str, int] = {}
        self._last_frame_diagnostics: dict[str, Any] = {}

    @staticmethod
    def head_degrees_to_radians(values) -> np.ndarray:
        return np.deg2rad(_vector(values, 2, "head")).astype(np.float32)

    @staticmethod
    def gripper_percent_to_unit(values) -> np.ndarray:
        raw = _vector(values, 2, "gripper")
        if np.any((raw < 0.0) | (raw > 100.0)):
            raise ValueError(f"gripper values must be within 0..100, got {raw.tolist()}")
        return (raw / 100.0).astype(np.float32)

    def add(
        self, key: str, value: Any, *, receive_time_ns: int | None = None, source_time_ns: int | None = None
    ) -> None:
        if key not in self._buffers:
            raise KeyError(key)
        timestamp = time.monotonic_ns() if receive_time_ns is None else int(receive_time_ns)
        with self._lock:
            self._buffers[key].append(TimedValue(timestamp, value, source_time_ns))
            self._counts[key] += 1
            self._first_receive_ns.setdefault(key, timestamp)
            self._last_receive_ns[key] = timestamp

    def try_build_frame(self) -> SynchronizedFrame | None:
        with self._lock:
            if not self._buffers["left_eye"]:
                return None
            anchor = self._buffers["left_eye"][-1]
            if anchor.receive_time_ns <= self._last_anchor_ns:
                return None

            selected: dict[str, TimedValue] = {"left_eye": anchor}
            for key in CAMERAS[1:]:
                sample = _nearest(self._buffers[key], anchor.receive_time_ns)
                if sample is None or abs(sample.receive_time_ns - anchor.receive_time_ns) > self.image_tolerance_ns:
                    return None
                selected[key] = sample

            for key in ("arm_state", "head_state", "arm_action", "head_action"):
                sample = _nearest(self._buffers[key], anchor.receive_time_ns)
                if sample is None or abs(sample.receive_time_ns - anchor.receive_time_ns) > self.joint_max_age_ns:
                    return None
                selected[key] = sample
            for key in ("gripper_state", "gripper_action"):
                sample = _latest_not_after(self._buffers[key], anchor.receive_time_ns)
                if sample is None or anchor.receive_time_ns - sample.receive_time_ns > self.gripper_max_age_ns:
                    return None
                selected[key] = sample

            state = np.concatenate(
                [
                    _vector(selected["arm_state"].value, 14, "arm_state"),
                    self.head_degrees_to_radians(selected["head_state"].value),
                    self.gripper_percent_to_unit(selected["gripper_state"].value),
                ]
            ).astype(np.float32)
            action = np.concatenate(
                [
                    _vector(selected["arm_action"].value, 14, "arm_action"),
                    self.head_degrees_to_radians(selected["head_action"].value),
                    self.gripper_percent_to_unit(selected["gripper_action"].value),
                ]
            ).astype(np.float32)
            images = {key: np.asarray(selected[key].value, dtype=np.uint8) for key in CAMERAS}
            times = {key: item.receive_time_ns for key, item in selected.items()}
            image_times = [times[key] for key in CAMERAS]
            diagnostics = {
                "anchor_receive_time_ns": anchor.receive_time_ns,
                "receive_time_ns": times,
                "source_time_ns": {key: item.source_time_ns for key, item in selected.items()},
                "image_skew_ms": (max(image_times) - min(image_times)) / 1e6,
                "gripper_state_raw": _vector(selected["gripper_state"].value, 2, "gripper_state").tolist(),
                "gripper_action_raw": _vector(selected["gripper_action"].value, 2, "gripper_action").tolist(),
            }
            self._last_anchor_ns = anchor.receive_time_ns
            self._counts["frames_built"] += 1
            self._last_frame_diagnostics = diagnostics
            return SynchronizedFrame(anchor.receive_time_ns, images, state, action, diagnostics)

    def health(self, *, now_ns: int | None = None) -> dict[str, Any]:
        now = time.monotonic_ns() if now_ns is None else now_ns
        with self._lock:
            required = (*CAMERAS, *NUMERIC_KEYS)
            missing = [key for key in required if not self._buffers[key]]
            stale = []
            for key in required:
                if key not in self._last_receive_ns:
                    continue
                limit = self.gripper_max_age_ns if "gripper" in key else max(self.joint_max_age_ns, 100_000_000)
                if now - self._last_receive_ns[key] > limit:
                    stale.append(key)
            rates = {}
            for key, count in self._counts.items():
                if key == "frames_built" or key not in self._first_receive_ns:
                    continue
                elapsed = max((self._last_receive_ns[key] - self._first_receive_ns[key]) / 1e9, 1e-9)
                rates[key] = round((count - 1) / elapsed, 1) if count > 1 else 0.0
            return {
                "ready": not missing and not stale,
                "missing": missing,
                "stale": stale,
                "rates_hz": rates,
                "frames_built": self._counts["frames_built"],
                "last_frame": dict(self._last_frame_diagnostics),
            }


def _vector(values, dimension: int, name: str) -> np.ndarray:
    result = np.asarray(values, dtype=np.float32)
    if result.shape != (dimension,):
        raise ValueError(f"{name} must have shape ({dimension},), got {result.shape}")
    if not np.all(np.isfinite(result)):
        raise ValueError(f"{name} contains non-finite values")
    return result


def _nearest(buffer: deque[TimedValue], timestamp_ns: int) -> TimedValue | None:
    return min(buffer, key=lambda sample: abs(sample.receive_time_ns - timestamp_ns), default=None)


def _latest_not_after(buffer: deque[TimedValue], timestamp_ns: int) -> TimedValue | None:
    return next((sample for sample in reversed(buffer) if sample.receive_time_ns <= timestamp_ns), None)
