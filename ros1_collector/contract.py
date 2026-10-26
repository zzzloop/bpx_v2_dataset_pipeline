"""Frozen FIRST-generation mapping, identical to the existing ROS1 inference bridge.

Do not substitute BPX v2's arm/head/gripper order or percent gripper units.
No limit clipping, smoothing, hardware publishers or fake feedback.
"""
import math

import numpy as np

CAMERAS = ("left_eye", "left_wrist", "right_wrist")
STREAMS = CAMERAS + ("damiao", "feetech", "command")
MOTOR_NAMES = tuple(
    ["eyou_motor%d" % i for i in range(1, 4)]
    + ["damiao_motor%d" % i for i in range(1, 9)]
    + ["feetech_motor%d" % i for i in range(1, 11)]
)
JOINT_NAMES = (
    ["ArmL%02d_Joint" % i for i in range(2, 9)] + ["LeftGripper_1DoF"]
    + ["ArmR%02d_Joint" % i for i in range(2, 9)] + ["RightGripper_1DoF"]
    + ["Head02_Joint", "Head03_Joint"]
)


def vector(values, dimension):
    result = np.asarray(values, dtype=np.float32)
    if result.shape != (dimension,) or not np.isfinite(result).all():
        raise ValueError("expected %d finite positions, got %s" % (dimension, result.shape))
    return result


def gripper_legacy_metres(angle):
    # Two old simulated finger slots, each 0.04 - angle/0.8923*0.04.
    # This is their SUM, not raw motor radians, percent, or a newly defined width.
    return 0.08 - float(angle) / 0.8923 * 0.08


def feedback_to_state(damiao, feetech):
    d, f = vector(damiao, 8), vector(feetech, 10)
    return np.asarray([
        *d[:4], *f[2:5], gripper_legacy_metres(f[8]),
        *d[4:8], *f[5:8], gripper_legacy_metres(f[9]), *f[:2],
    ], dtype=np.float32)


def canonical_command(positions, names=()):
    result = vector(positions, 21)
    if names and any(names):
        if len(names) != 21 or len(set(names)) != 21 or set(names) != set(MOTOR_NAMES):
            raise ValueError("command.name differs from the known 21-motor contract")
        result = result[[names.index(name) for name in MOTOR_NAMES]]
    return result


def command_to_action(command):
    c = vector(command, 21)
    return np.asarray([
        *c[3:7], *c[13:16], gripper_legacy_metres(c[19]),
        *c[7:11], *c[16:19], gripper_legacy_metres(c[20]), *c[11:13],
    ], dtype=np.float32)


def decode_image(message, width=640, height=360):
    if message.width != width or message.height != height:
        raise ValueError("image must be %dx%d, got %dx%d" % (width, height, message.width, message.height))
    if message.encoding.lower() not in ("rgb8", "bgr8"):
        raise ValueError("only rgb8/bgr8 accepted, got " + message.encoding)
    if message.step < width * 3 or len(message.data) != message.step * height:
        raise ValueError("invalid image step/data length")
    rows = np.frombuffer(bytes(message.data), dtype=np.uint8).reshape(height, message.step)
    image = rows[:, :width * 3].reshape(height, width, 3)
    if message.encoding.lower() == "bgr8":
        image = image[:, :, ::-1]
    return np.ascontiguousarray(image).copy()


def validate_config(config):
    if (config["fps"], config["width"], config["height"]) != (30, 640, 360):
        raise ValueError("this FIRST-generation contract is 640x360 at 30 Hz")
    if set(config["topics"]) != set(STREAMS):
        raise ValueError("topic keys must be " + ", ".join(STREAMS))
    if any(not isinstance(topic, str) or not topic.startswith("/") for topic in config["topics"].values()):
        raise ValueError("topics must be absolute ROS1 topic names")
    for key in ("image_skew_ms", "joint_max_age_ms", "max_frame_gap_ms",
                "minimum_effective_fps", "maximum_effective_fps"):
        value = config[key]
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError("invalid " + key)
    if not config["minimum_effective_fps"] <= 30 <= config["maximum_effective_fps"]:
        raise ValueError("effective FPS range must contain 30")
