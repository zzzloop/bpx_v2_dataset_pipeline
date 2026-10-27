"""Regression specifications. Execute on the robot/server, NOT the local desktop."""
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from ros1_collector.contract import (
    CAMERAS, STREAMS, MOTOR_NAMES, canonical_command, command_to_action, decode_image, feedback_to_state, validate_config,
)
from ros1_collector.source import Ros1Source
from ros1_collector.writer import features


def test_hardware_feedback_and_commands_agree_in_old_effective18_order():
    damiao = np.arange(8, dtype=np.float32) * .1
    feetech = np.arange(10, dtype=np.float32) * .03
    hardware = np.concatenate([np.zeros(3), damiao, feetech])
    state = feedback_to_state(damiao, feetech)
    np.testing.assert_allclose(state, command_to_action(hardware))
    np.testing.assert_allclose(state[:7], [*damiao[:4], *feetech[2:5]])
    np.testing.assert_allclose(state[8:15], [*damiao[4:], *feetech[5:8]])
    np.testing.assert_allclose(state[16:], feetech[:2])
    assert np.isclose(state[7], .08 - feetech[8] / .8923 * .08)
    assert np.isclose(command_to_action([0.] * 19 + [.8923, 0.])[7], 0, atol=1e-8)
    assert np.isclose(command_to_action([0.] * 21)[15], .08)


def test_named_command_is_reordered_and_unknown_names_rejected():
    values = np.arange(21, dtype=np.float32)
    np.testing.assert_array_equal(canonical_command(values[::-1], list(MOTOR_NAMES)[::-1]), values)
    with pytest.raises(ValueError):
        canonical_command(values, ["unknown"] * 21)


def test_rgb_bgr_and_row_padding():
    message = SimpleNamespace(width=2, height=1, step=8, encoding="bgr8",
                              data=bytes([1, 2, 3, 4, 5, 6, 99, 99]))
    image = decode_image(message, width=2, height=1)
    np.testing.assert_array_equal(image, [[[3, 2, 1], [6, 5, 4]]])
    message.height = 480
    with pytest.raises(ValueError):
        decode_image(message)


def test_source_never_reuses_camera_frames_or_substitutes_feedback_for_action():
    config = json.loads(Path(__file__).with_name("config.json").read_text())
    validate_config(config)
    source = Ros1Source(config)
    import time
    stamp = time.monotonic_ns()
    for key in source.buffers:
        value = (np.zeros((360, 640, 3), dtype=np.uint8) if key in CAMERAS
                 else np.zeros(8 if key == "damiao" else 10 if key == "feetech" else 21))
        source.buffers[key].append((stamp - (1 if key in ("damiao", "feetech", "command") else 0), 0, 1, value))
    frame = source.sample()
    assert frame is not None and frame["action"].shape == (18,)
    assert set(frame["images"]) == set(CAMERAS)
    assert len(frame["bpx.receive_time_ns"]) == len(frame["bpx.source_time_ns"]) == len(STREAMS) == 7
    assert source.sample() is None
    # Missing right-eye messages cannot be silently filled with the left eye.
    right_eye = source.buffers["right_eye"].pop()
    source.used.clear()
    assert source.sample() is None
    source.buffers["right_eye"].append(right_eye)
    source.buffers["command"].clear()
    source.used.clear()
    assert source.sample() is None


def test_video_features_keep_first_generation_training_contract():
    schema = features()
    assert schema["observation.state"]["shape"] == [18]
    assert schema["action"]["names"][7] == "LeftGripper_1DoF"
    assert schema["action"]["names"][15] == "RightGripper_1DoF"
    cameras = [ft for ft in schema.values() if ft["dtype"] == "video"]
    assert len(cameras) == 4 and all(ft["shape"] == [360, 640, 3] for ft in cameras)
    assert schema["bpx.receive_time_ns"]["names"] == list(STREAMS)
    assert schema["bpx.receive_time_ns"]["shape"] == [7]
