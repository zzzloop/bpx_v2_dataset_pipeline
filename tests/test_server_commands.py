from __future__ import annotations

import pathlib

import pytest

from bpx_v2_dataset_pipeline.server.commands import build_audit, build_normalize, build_train


def _openpi_root(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "openpi"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "compute_norm_stats.py").write_text("", encoding="utf-8")
    (root / "scripts" / "train.py").write_text("", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    return root


def test_audit_command_exposes_full_video_validation(tmp_path: pathlib.Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    spec = build_audit(
        tmp_path,
        {
            "dataset_root": str(dataset),
            "report_path": str(tmp_path / "audit.json"),
            "workers": 32,
            "video_check": "full",
        },
    )
    assert "--video-check" in spec.argv
    assert spec.argv[spec.argv.index("--video-check") + 1] == "full"


def test_normalization_defaults_to_32_workers_without_sampling(tmp_path: pathlib.Path) -> None:
    root = _openpi_root(tmp_path)
    spec = build_normalize(
        {
            "openpi_root": str(root),
            "config_name": "pi05_bpx_v2_gripper",
            "workers": 32,
            "hf_lerobot_home": str(tmp_path / "lerobot"),
        }
    )
    assert spec.argv[-2:] == ("--num-workers", "32")
    assert "--max-frames" not in spec.argv
    assert spec.env["HF_LEROBOT_HOME"] == str((tmp_path / "lerobot").resolve())


def test_training_command_preserves_validated_two_gpu_contract(tmp_path: pathlib.Path) -> None:
    root = _openpi_root(tmp_path)
    values = {
        "openpi_root": str(root),
        "config_name": "pi05_bpx_v2_gripper",
        "exp_name": "gripper_bs2",
        "checkpoint_base_dir": str(tmp_path / "checkpoints"),
        "cuda_devices": "2,3",
        "memory_fraction": 0.96,
        "batch_size": 2,
        "num_train_steps": 200000,
        "fsdp_devices": 2,
        "save_interval": 5000,
        "keep_period": 25000,
        "mode": "resume",
    }
    spec = build_train(values)
    assert spec.argv[-1] == "--resume"
    assert "--batch-size=2" in spec.argv
    assert "--num-train-steps=200000" in spec.argv
    assert spec.env["CUDA_VISIBLE_DEVICES"] == "2,3"
    assert spec.env["XLA_PYTHON_CLIENT_MEM_FRACTION"] == "0.96"
    assert spec.total_units == 200000


def test_training_rejects_device_and_batch_mismatch(tmp_path: pathlib.Path) -> None:
    root = _openpi_root(tmp_path)
    values = {
        "openpi_root": str(root),
        "config_name": "valid",
        "exp_name": "valid",
        "checkpoint_base_dir": str(tmp_path / "checkpoints"),
        "cuda_devices": "2,3",
        "memory_fraction": 0.96,
        "batch_size": 1,
        "num_train_steps": 10,
        "fsdp_devices": 2,
        "save_interval": 5,
        "keep_period": 10,
        "mode": "overwrite",
    }
    with pytest.raises(ValueError, match="batch size"):
        build_train(values)
