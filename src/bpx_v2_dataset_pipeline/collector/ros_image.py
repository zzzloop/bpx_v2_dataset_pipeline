from __future__ import annotations

import numpy as np


class RosImageError(ValueError):
    pass


def image_message_to_rgb(message, *, expected_width: int = 640, expected_height: int = 480) -> np.ndarray:
    """Convert sensor_msgs/Image to packed RGB without depending on cv_bridge."""
    width = int(message.width)
    height = int(message.height)
    if (width, height) != (expected_width, expected_height):
        raise RosImageError(f"expected {expected_width}x{expected_height}, got {width}x{height}")

    encoding = str(message.encoding).lower()
    channels_by_encoding = {"rgb8": 3, "bgr8": 3, "rgba8": 4, "bgra8": 4, "mono8": 1}
    if encoding not in channels_by_encoding:
        raise RosImageError(f"unsupported image encoding: {encoding!r}")
    channels = channels_by_encoding[encoding]
    step = int(message.step)
    packed_step = width * channels
    if step < packed_step:
        raise RosImageError(f"image step {step} is smaller than packed row {packed_step}")

    raw = np.frombuffer(message.data, dtype=np.uint8)
    required = step * height
    if raw.size < required:
        raise RosImageError(f"image data has {raw.size} bytes, expected at least {required}")
    rows = raw[:required].reshape(height, step)[:, :packed_step]
    pixels = rows.reshape(height, width, channels)
    if encoding == "rgb8":
        rgb = pixels
    elif encoding == "bgr8":
        rgb = pixels[:, :, ::-1]
    elif encoding == "rgba8":
        rgb = pixels[:, :, :3]
    elif encoding == "bgra8":
        rgb = pixels[:, :, [2, 1, 0]]
    else:
        rgb = np.repeat(pixels, 3, axis=2)
    return np.ascontiguousarray(rgb)
