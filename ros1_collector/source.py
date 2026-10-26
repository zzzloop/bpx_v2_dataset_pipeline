"""Read-only rospy subscriptions. A bounded buffer pairs each video frame once."""
from collections import deque
import threading
import time

from ros1_collector.contract import (
    CAMERAS, STREAMS, canonical_command, command_to_action, decode_image, feedback_to_state, vector,
)


class Ros1Source:
    def __init__(self, config):
        self.config = config
        self.lock = threading.Lock()
        self.buffers = {key: deque(maxlen=8 if key in CAMERAS else 64) for key in STREAMS}
        self.counts = {key: 0 for key in STREAMS}
        self.first = {}
        self.errors = {}
        self.used = {}
        self.subscribers = []

    def start(self):
        import rospy
        from sensor_msgs.msg import Image, JointState
        rospy.init_node("bpx_v1_lerobot_collector", anonymous=True, disable_signals=True)
        for key, topic in self.config["topics"].items():
            self.subscribers.append(rospy.Subscriber(
                topic, Image if key in CAMERAS else JointState, self.receive,
                callback_args=key, queue_size=2, buff_size=4 * 1024 * 1024, tcp_nodelay=True,
            ))

    def receive(self, message, key):
        received = time.monotonic_ns()
        try:
            if key in CAMERAS:
                value = decode_image(message, self.config["width"], self.config["height"])
            elif key == "command":
                value = canonical_command(message.position, list(message.name))
            else:
                value = vector(message.position, 8 if key == "damiao" else 10)
            stamp = int(message.header.stamp.to_nsec())
            with self.lock:
                self.counts[key] += 1
                self.first.setdefault(key, received)
                self.buffers[key].append((received, stamp, self.counts[key], value))
                self.errors.pop(key, None)
        except Exception as error:
            with self.lock:
                self.errors[key] = str(error)

    def health(self):
        now = time.monotonic_ns()
        with self.lock:
            missing = [key for key in STREAMS if not self.buffers[key]]
            stale = [key for key in STREAMS if self.buffers[key] and
                     now - self.buffers[key][-1][0] > (250e6 if key in CAMERAS else self.config["joint_max_age_ms"] * 1e6)]
            rates = {key: round((self.counts[key] - 1) * 1e9 / max(1, self.buffers[key][-1][0] - self.first[key]), 1)
                     for key in STREAMS if self.counts[key] > 1}
            return {"ready": not missing and not stale and not self.errors, "missing": missing,
                    "stale": stale, "rates_hz": rates, "errors": dict(self.errors)}

    def reset(self):
        with self.lock:
            self.used = {key: self.buffers[key][-1][2] for key in CAMERAS if self.buffers[key]}

    def sample(self):
        with self.lock:
            if self.errors or not self.buffers["left_eye"]:
                return None
            anchor = self.buffers["left_eye"][-1]
            if anchor[2] <= self.used.get("left_eye", 0):
                return None
            selected = {"left_eye": anchor}
            for key in CAMERAS[1:]:
                unused = [item for item in self.buffers[key] if item[2] > self.used.get(key, 0)]
                candidate = min(unused, key=lambda item: abs(item[0] - anchor[0]), default=None)
                if candidate is None or abs(candidate[0] - anchor[0]) > self.config["image_skew_ms"] * 1e6:
                    return None
                selected[key] = candidate
            for key in ("damiao", "feetech", "command"):
                # Causal zero-order hold, NOT future targets or feedback substituted as actions.
                candidate = next((item for item in reversed(self.buffers[key]) if item[0] <= anchor[0]), None)
                if candidate is None or anchor[0] - candidate[0] > self.config["joint_max_age_ms"] * 1e6:
                    return None
                selected[key] = candidate
            if time.monotonic_ns() - anchor[0] > 250_000_000:
                return None
            self.used = {key: selected[key][2] for key in CAMERAS}
            return {
                "capture_ns": anchor[0], "images": {key: selected[key][3] for key in CAMERAS},
                "observation.state": feedback_to_state(selected["damiao"][3], selected["feetech"][3]),
                "action": command_to_action(selected["command"][3]),
                "bpx.hardware_state": [*selected["damiao"][3], *selected["feetech"][3]],
                "bpx.hardware_action": selected["command"][3],
                "bpx.receive_time_ns": [selected[key][0] for key in STREAMS],
                "bpx.source_time_ns": [selected[key][1] for key in STREAMS],
            }

    def close(self):
        for subscriber in self.subscribers:
            subscriber.unregister()
