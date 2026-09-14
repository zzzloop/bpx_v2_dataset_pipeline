import numpy as np

from bpx_v2_dataset_pipeline.collector.synchronizer import FrameSynchronizer


def add_complete_sample(sync: FrameSynchronizer, anchor_ns: int) -> None:
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    for offset, key in enumerate(("left_eye", "right_eye", "left_wrist", "right_wrist")):
        sync.add(key, image, receive_time_ns=anchor_ns + offset * 1_000_000)
    sync.add("arm_state", np.arange(14), receive_time_ns=anchor_ns)
    sync.add("head_state", [180, -90], receive_time_ns=anchor_ns)
    sync.add("gripper_state", [25, 75], receive_time_ns=anchor_ns - 20_000_000)
    sync.add("arm_action", np.arange(14) + 20, receive_time_ns=anchor_ns)
    sync.add("head_action", [90, 45], receive_time_ns=anchor_ns)
    sync.add("gripper_action", [0, 100], receive_time_ns=anchor_ns - 10_000_000)


def test_builds_18d_frame_with_units_and_order() -> None:
    sync = FrameSynchronizer()
    add_complete_sample(sync, 1_000_000_000)
    frame = sync.try_build_frame()
    assert frame is not None
    assert frame.state.shape == frame.action.shape == (18,)
    np.testing.assert_allclose(frame.state[:14], np.arange(14))
    np.testing.assert_allclose(frame.state[14:16], [np.pi, -np.pi / 2], rtol=1e-6)
    np.testing.assert_allclose(frame.state[16:], [0.25, 0.75])
    np.testing.assert_allclose(frame.action[16:], [0, 1])
    assert frame.diagnostics["gripper_state_raw"] == [25.0, 75.0]
    assert frame.diagnostics["image_skew_ms"] == 3.0


def test_gripper_uses_past_sample_and_rejects_stale_data() -> None:
    sync = FrameSynchronizer(gripper_max_age_ms=50)
    anchor = 1_000_000_000
    add_complete_sample(sync, anchor)
    sync._buffers["gripper_state"].clear()
    sync.add("gripper_state", [10, 10], receive_time_ns=anchor + 1_000_000)
    assert sync.try_build_frame() is None

    sync.add("gripper_state", [10, 10], receive_time_ns=anchor - 60_000_000)
    assert sync.try_build_frame() is None


def test_health_names_missing_streams() -> None:
    sync = FrameSynchronizer()
    health = sync.health(now_ns=1)
    assert health["ready"] is False
    assert "left_eye" in health["missing"]
    assert "gripper_action" in health["missing"]
