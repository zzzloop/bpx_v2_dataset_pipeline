from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Callable
from typing import Any

from bpx_v2_dataset_pipeline.collector.backend import CaptureBackend, SynchronizedFrame
from bpx_v2_dataset_pipeline.collector.ros_image import RosImageError, image_message_to_rgb
from bpx_v2_dataset_pipeline.collector.synchronizer import FrameSynchronizer


class Ros2JazzyCaptureBackend(CaptureBackend):
    """Subscriber-only ROS2 Jazzy backend. It deliberately creates no publishers."""

    def __init__(self, contract: dict[str, Any]) -> None:
        sampling = contract["sampling"]
        self.contract = contract
        self.synchronizer = FrameSynchronizer(
            image_tolerance_ms=float(sampling["image_sync_tolerance_ms"]),
            joint_max_age_ms=float(sampling["joint_max_age_ms"]),
            gripper_max_age_ms=float(sampling["gripper_max_age_ms"]),
        )
        self._queue: asyncio.Queue[SynchronizedFrame] = asyncio.Queue(maxsize=int(sampling["queue_depth"]))
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._executor = None
        self._node = None
        self._closed = False
        self._started = False
        self._queue_drop_count = 0
        self._decode_error_count = 0
        self._last_error = ""

    @property
    def name(self) -> str:
        return "ros2-jazzy-subscriber"

    def _start(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._started:
            return
        try:
            import rclpy
            from rclpy.executors import MultiThreadedExecutor
            from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
            from sensor_msgs.msg import Image
            from stm32_ros_bridge_msgs.msg import (
                ArmJointCommand,
                ArmJointFeedback,
                GripperMove,
                GripperStatus,
                HeadJointCommand,
                HeadJointFeedback,
            )
        except ImportError as error:
            raise RuntimeError(
                "ROS2 Jazzy or stm32_ros_bridge_msgs is unavailable. Source /opt/ros/jazzy/setup.bash "
                "and the robot interface workspace before starting the collector."
            ) from error

        if not rclpy.ok():
            rclpy.init(args=None)
        self._loop = loop
        self._node = rclpy.create_node(self.contract["ros2"]["node_name"])
        reliable = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=100,
            reliability=ReliabilityPolicy.RELIABLE,
        )
        sensor = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=5,
            reliability=ReliabilityPolicy.BEST_EFFORT,
        )

        subscriptions: list[tuple[Any, str, Callable]] = [
            (ArmJointFeedback, "observations.arm", self._vector_callback("arm_state", 14)),
            (HeadJointFeedback, "observations.head", self._vector_callback("head_state", 2)),
            (GripperStatus, "observations.gripper", self._gripper_status_callback),
            (ArmJointCommand, "actions.arm", self._vector_callback("arm_action", 14)),
            (HeadJointCommand, "actions.head", self._vector_callback("head_action", 2)),
            (GripperMove, "actions.gripper", self._gripper_move_callback),
        ]
        for message_type, dotted_key, callback in subscriptions:
            section, key = dotted_key.split(".")
            topic = self.contract[section][key]["topic"]
            self._node.create_subscription(message_type, topic, callback, reliable)
        for camera_name, spec in self.contract["cameras"].items():
            self._node.create_subscription(Image, spec["topic"], self._image_callback(camera_name), sensor)

        self._executor = MultiThreadedExecutor(num_threads=8)
        self._executor.add_node(self._node)
        self._thread = threading.Thread(target=self._executor.spin, name="bpx-ros2-executor", daemon=True)
        self._thread.start()
        self._started = True

    def _vector_callback(self, key: str, dimension: int) -> Callable:
        def callback(message) -> None:
            try:
                values = list(message.position)
                if len(values) != dimension:
                    raise ValueError(f"{key}: expected {dimension} positions, got {len(values)}")
                self.synchronizer.add(key, values, source_time_ns=_source_time_ns(message))
                self._emit_if_ready()
            except (TypeError, ValueError) as error:
                self._record_error(error)

        return callback

    def _gripper_status_callback(self, message) -> None:
        try:
            grippers = list(message.grippers)
            if len(grippers) != 2:
                raise ValueError(f"gripper_state: expected 2 grippers, got {len(grippers)}")
            self.synchronizer.add(
                "gripper_state",
                [grippers[0].position, grippers[1].position],
                source_time_ns=_source_time_ns(message),
            )
            self._emit_if_ready()
        except (AttributeError, TypeError, ValueError) as error:
            self._record_error(error)

    def _gripper_move_callback(self, message) -> None:
        try:
            grippers = list(message.grippers)
            if len(grippers) != 2:
                raise ValueError(f"gripper_action: expected 2 grippers, got {len(grippers)}")
            self.synchronizer.add(
                "gripper_action",
                [grippers[0].position, grippers[1].position],
                source_time_ns=_source_time_ns(message),
            )
            self._emit_if_ready()
        except (AttributeError, TypeError, ValueError) as error:
            self._record_error(error)

    def _image_callback(self, camera_name: str) -> Callable:
        def callback(message) -> None:
            try:
                image = image_message_to_rgb(message)
                self.synchronizer.add(camera_name, image, source_time_ns=_source_time_ns(message))
                self._emit_if_ready()
            except (RosImageError, TypeError, ValueError) as error:
                self._decode_error_count += 1
                self._record_error(error)

        return callback

    def _record_error(self, error: Exception) -> None:
        self._last_error = f"{type(error).__name__}: {error}"

    def _emit_if_ready(self) -> None:
        frame = self.synchronizer.try_build_frame()
        if frame is None or self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._enqueue, frame)

    def _enqueue(self, frame: SynchronizedFrame) -> None:
        if self._queue.full():
            self._queue.get_nowait()
            self._queue_drop_count += 1
        self._queue.put_nowait(frame)

    def reset_capture_queue(self) -> None:
        while not self._queue.empty():
            self._queue.get_nowait()

    async def frames(self) -> AsyncIterator[SynchronizedFrame]:
        await self.start()
        while not self._closed:
            yield await self._queue.get()

    async def start(self) -> None:
        self._start(asyncio.get_running_loop())

    def health(self) -> dict:
        health = self.synchronizer.health()
        health.update(
            {
                "started": self._started,
                "subscriber_only": True,
                "queue_depth": self._queue.qsize(),
                "drop_counts": {
                    "queue": self._queue_drop_count,
                    "image_decode": self._decode_error_count,
                },
                "last_error": self._last_error,
            }
        )
        return health

    async def close(self) -> None:
        self._closed = True
        if self._executor is not None:
            self._executor.shutdown(timeout_sec=2.0)
        if self._node is not None:
            self._node.destroy_node()
        if self._thread is not None:
            await asyncio.to_thread(self._thread.join, 2.0)


def _source_time_ns(message) -> int | None:
    try:
        stamp = message.header.stamp
        value = int(stamp.sec) * 1_000_000_000 + int(stamp.nanosec)
        return value or None
    except AttributeError:
        return None
