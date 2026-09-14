from __future__ import annotations

import pathlib
import tomllib
from typing import Any


class HardwareContractError(ValueError):
    pass


def load_hardware_contract(path: pathlib.Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        contract = tomllib.load(stream)
    _validate_arm_order(contract)
    _validate_frozen_contract(contract)
    return contract


def _validate_arm_order(contract: dict[str, Any]) -> None:
    try:
        arm = contract["actions"]["arm"]
    except KeyError as error:
        raise HardwareContractError("actions.arm is required") from error
    expected = [*(f"left_arm_{index}" for index in range(7)), *(f"right_arm_{index}" for index in range(7))]
    if arm.get("dimension") != 14 or arm.get("order") != expected:
        raise HardwareContractError("arm action must be 14D: left[0:7], then right[0:7]")
    training_schema = contract.get("training_schema", {})
    expected_training = [*expected, "head_pan", "head_tilt", "left_gripper", "right_gripper"]
    for prefix in ("action", "state"):
        if training_schema.get(f"{prefix}_dimension") != 18:
            raise HardwareContractError(f"training {prefix} must be 18D")
        if training_schema.get(f"{prefix}_order") != expected_training:
            raise HardwareContractError(f"training {prefix} order must be arms, head, then grippers")


def _validate_frozen_contract(contract: dict[str, Any]) -> None:
    if contract.get("contract_status") != "production_ready":
        raise HardwareContractError("only a production_ready hardware contract may drive real collection")
    if contract.get("ros2", {}).get("subscriber_only") is not True:
        raise HardwareContractError("collector hardware contract must be subscriber_only")

    expected = {
        ("actions", "arm"): ("/arm_joint_command", "stm32_ros_bridge_msgs/msg/ArmJointCommand", 14),
        ("actions", "head"): ("/head_joint_command", "stm32_ros_bridge_msgs/msg/HeadJointCommand", 2),
        ("actions", "gripper"): ("/gripper_move", "stm32_ros_bridge_msgs/msg/GripperMove", 2),
        ("observations", "arm"): ("/arm_joint_feedback", "stm32_ros_bridge_msgs/msg/ArmJointFeedback", 14),
        ("observations", "head"): ("/head_joint_feedback", "stm32_ros_bridge_msgs/msg/HeadJointFeedback", 2),
        ("observations", "gripper"): ("/gripper_status", "stm32_ros_bridge_msgs/msg/GripperStatus", 2),
    }
    for (section, name), (topic, message_type, dimension) in expected.items():
        spec = contract.get(section, {}).get(name, {})
        if (spec.get("topic"), spec.get("message_type"), spec.get("dimension")) != (
            topic,
            message_type,
            dimension,
        ):
            raise HardwareContractError(f"frozen contract mismatch at {section}.{name}")

    camera_topics = {
        "left_eye": "/data/left_eye_image",
        "right_eye": "/data/right_eye_image",
        "left_wrist": "/data/left_wrist_image",
        "right_wrist": "/data/right_wrist_image",
    }
    for name, topic in camera_topics.items():
        spec = contract.get("cameras", {}).get(name, {})
        if spec.get("topic") != topic or (spec.get("width"), spec.get("height"), spec.get("fps")) != (
            640,
            480,
            30.0,
        ):
            raise HardwareContractError(f"frozen camera contract mismatch at cameras.{name}")


def summarize_hardware_contract(contract: dict[str, Any]) -> dict[str, Any]:
    missing: list[str] = []
    for section_name in ("actions", "observations", "cameras"):
        for name, spec in contract.get(section_name, {}).items():
            if not spec.get("required", False):
                continue
            for field in ("topic", "message_type"):
                if not str(spec.get(field, "")).strip():
                    missing.append(f"{section_name}.{name}.{field}")
            if section_name == "cameras" and not str(spec.get("encoding", "")).strip():
                missing.append(f"{section_name}.{name}.encoding")

    actions = contract.get("actions", {})
    selected_actions = {name: spec for name, spec in actions.items() if spec.get("required", False)}
    return {
        "schema_version": contract.get("schema_version", ""),
        "declared_status": contract.get("contract_status", "unknown"),
        "production_ready": not missing,
        "arm_action_dimension": actions.get("arm", {}).get("dimension"),
        "arm_action_order": actions.get("arm", {}).get("order", []),
        "selected_action_dimension": sum(int(spec.get("dimension", 0)) for spec in selected_actions.values()),
        "selected_actions": {name: int(spec.get("dimension", 0)) for name, spec in selected_actions.items()},
        "training_action_order": contract.get("training_schema", {}).get("action_order", []),
        "known_action_topics": {name: spec.get("topic", "") for name, spec in actions.items() if spec.get("topic")},
        "cameras": {
            name: {
                "topic": spec.get("topic", ""),
                "width": spec.get("width"),
                "height": spec.get("height"),
                "encoding": spec.get("encoding", ""),
                "source_status": spec.get("source_status", "unknown"),
            }
            for name, spec in contract.get("cameras", {}).items()
        },
        "missing": missing,
        "sampling": contract.get("sampling", {}),
        "subscriber_only": contract.get("ros2", {}).get("subscriber_only") is True,
    }
