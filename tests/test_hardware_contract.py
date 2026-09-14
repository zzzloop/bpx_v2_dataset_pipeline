import pathlib

from bpx_v2_dataset_pipeline.collector.hardware_contract import (
    load_hardware_contract,
    summarize_hardware_contract,
)

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_ros2_contract_freezes_the_confirmed_arm_order() -> None:
    contract = load_hardware_contract(PROJECT_ROOT / "configs" / "ros2-jazzy-hardware.toml")
    summary = summarize_hardware_contract(contract)
    assert summary["arm_action_dimension"] == 14
    assert summary["arm_action_order"] == [
        *(f"left_arm_{index}" for index in range(7)),
        *(f"right_arm_{index}" for index in range(7)),
    ]


def test_ros2_contract_is_complete_and_subscriber_only() -> None:
    contract = load_hardware_contract(PROJECT_ROOT / "configs" / "ros2-jazzy-hardware.toml")
    summary = summarize_hardware_contract(contract)
    assert summary["production_ready"] is True
    assert summary["selected_actions"] == {"arm": 14, "head": 2, "gripper": 2}
    assert summary["selected_action_dimension"] == 18
    assert summary["training_action_order"][-4:] == ["head_pan", "head_tilt", "left_gripper", "right_gripper"]
    assert summary["missing"] == []
    assert summary["subscriber_only"] is True
    assert summary["cameras"]["left_eye"]["source_status"] == "confirmed"
    assert summary["cameras"]["left_wrist"]["height"] == 480


def test_ros2_backend_has_no_publisher_or_robot_command_output() -> None:
    source = (PROJECT_ROOT / "src" / "bpx_v2_dataset_pipeline" / "collector" / "ros2_backend.py").read_text()
    assert "create_subscription" in source
    assert "create_publisher" not in source
    assert ".publish(" not in source
