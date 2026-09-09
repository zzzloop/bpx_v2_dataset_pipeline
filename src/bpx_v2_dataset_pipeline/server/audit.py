from __future__ import annotations

import argparse
import json
import pathlib
from concurrent import futures
from typing import Any

import numpy as np


def _read_json_lines(path: pathlib.Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _audit_parquet(path: pathlib.Path, numeric_keys: tuple[str, ...]) -> dict[str, Any]:
    try:
        import pyarrow.parquet as pq
    except ImportError as error:
        raise RuntimeError("Install the server extra: uv sync --extra server") from error
    table = pq.read_table(path, columns=[*numeric_keys, "episode_index", "frame_index", "timestamp"])
    if table.num_rows < 1:
        raise ValueError(f"Empty episode parquet: {path}")
    report: dict[str, Any] = {"path": str(path), "frames": table.num_rows}
    for key in numeric_keys:
        values = np.asarray(table[key].combine_chunks().to_pylist(), dtype=np.float32)
        if values.ndim != 2 or not np.all(np.isfinite(values)):
            raise ValueError(f"{path}: {key} must be a finite (T, D) matrix")
        report[f"{key}_dim"] = values.shape[1]
    episode_indices = np.asarray(table["episode_index"].combine_chunks().to_pylist())
    frame_indices = np.asarray(table["frame_index"].combine_chunks().to_pylist())
    timestamps = np.asarray(table["timestamp"].combine_chunks().to_pylist(), dtype=np.float64)
    if np.unique(episode_indices).size != 1:
        raise ValueError(f"{path}: multiple episode indices in one parquet")
    if not np.array_equal(frame_indices, np.arange(table.num_rows)):
        raise ValueError(f"{path}: frame indices are not contiguous")
    if np.any(np.diff(timestamps) <= 0):
        raise ValueError(f"{path}: timestamps are not strictly increasing")
    report["episode_index"] = int(episode_indices[0])
    return report


def audit_dataset(root: pathlib.Path, workers: int) -> dict[str, Any]:
    info_path = root / "meta" / "info.json"
    episodes_path = root / "meta" / "episodes.jsonl"
    tasks_path = root / "meta" / "tasks.jsonl"
    for path in (info_path, episodes_path, tasks_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    info = json.loads(info_path.read_text(encoding="utf-8"))
    episodes = _read_json_lines(episodes_path)
    tasks = _read_json_lines(tasks_path)
    features = info.get("features", {})
    for key in ("observation.state", "action"):
        if key not in features:
            raise ValueError(f"Missing required feature: {key}")
    camera_keys = sorted(key for key, feature in features.items() if feature.get("dtype") in {"image", "video"})
    parquet_files = sorted((root / "data").rglob("*.parquet"))
    if len(parquet_files) != len(episodes):
        raise ValueError(f"Parquet/episode mismatch: {len(parquet_files)} != {len(episodes)}")
    with futures.ProcessPoolExecutor(max_workers=workers) as executor:
        reports = list(
            executor.map(_audit_parquet, parquet_files, [("observation.state", "action")] * len(parquet_files))
        )
    total_frames = sum(report["frames"] for report in reports)
    if total_frames != int(info.get("total_frames", -1)):
        raise ValueError(f"Frame total mismatch: {total_frames} != {info.get('total_frames')}")
    if len(episodes) != int(info.get("total_episodes", -1)):
        raise ValueError("Episode total in info.json is inconsistent")
    video_keys = [key for key in camera_keys if features[key]["dtype"] == "video"]
    mp4_files = list((root / "videos").rglob("*.mp4")) if video_keys else []
    expected_videos = len(episodes) * len(video_keys)
    if len(mp4_files) != expected_videos:
        raise ValueError(f"MP4 count mismatch: {len(mp4_files)} != {expected_videos}")
    return {
        "root": str(root),
        "robot_type": info.get("robot_type"),
        "episodes": len(episodes),
        "frames": total_frames,
        "tasks": len(tasks),
        "camera_keys": camera_keys,
        "video_files": len(mp4_files),
        "workers": workers,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_root", type=pathlib.Path)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--report", type=pathlib.Path)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    report = audit_dataset(args.dataset_root.resolve(), args.workers)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    print("DATASET AUDIT PASS")


if __name__ == "__main__":
    main()
