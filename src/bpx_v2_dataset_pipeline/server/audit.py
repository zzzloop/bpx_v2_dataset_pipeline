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
    table = pq.read_table(path, columns=[*numeric_keys, "episode_index", "frame_index", "timestamp", "task_index"])
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
    task_indices, task_counts = np.unique(
        np.asarray(table["task_index"].combine_chunks().to_pylist(), dtype=np.int64), return_counts=True
    )
    report["task_frames"] = {
        str(int(index)): int(count) for index, count in zip(task_indices, task_counts, strict=True)
    }
    if table.num_rows > 1:
        deltas = np.diff(timestamps)
        report["timestamp_delta_median"] = float(np.median(deltas))
        report["timestamp_delta_max"] = float(np.max(deltas))
    return report


def _video_path(root: pathlib.Path, info: dict[str, Any], episode_index: int, key: str) -> pathlib.Path:
    template = info.get("video_path")
    if not template:
        raise ValueError("meta/info.json 缺少 video_path 模板")
    chunk_size = int(info.get("chunks_size", 1000))
    return root / template.format(
        episode_chunk=episode_index // chunk_size,
        episode_index=episode_index,
        video_key=key,
    )


def _audit_video(arguments: tuple[pathlib.Path, str, int, int, int, float, str]) -> dict[str, Any]:
    path, key, expected_frames, expected_height, expected_width, expected_fps, mode = arguments
    try:
        import av
    except ImportError as error:
        raise RuntimeError("视频审计需要服务器依赖: uv sync --extra server") from error
    if not path.is_file():
        raise FileNotFoundError(path)
    with av.open(str(path)) as container:
        if not container.streams.video:
            raise ValueError(f"{path}: 不包含视频流")
        stream = container.streams.video[0]
        if (stream.height, stream.width) != (expected_height, expected_width):
            raise ValueError(
                f"{path}: 视频尺寸 {(stream.height, stream.width)} != 元数据 {(expected_height, expected_width)}"
            )
        rate = float(stream.average_rate) if stream.average_rate else 0.0
        if rate and not np.isclose(rate, expected_fps, rtol=0.02, atol=0.05):
            raise ValueError(f"{path}: 视频 fps {rate:.6g} != 数据集 fps {expected_fps:.6g}")
        decoded_frames = None
        if mode == "full":
            decoded_frames = sum(1 for _ in container.decode(video=0))
            if decoded_frames != expected_frames:
                raise ValueError(f"{path}: 解码帧数 {decoded_frames} != episode 帧数 {expected_frames}")
    return {"path": str(path), "key": key, "decoded_frames": decoded_frames}


def audit_dataset(root: pathlib.Path, workers: int, *, video_check: str = "headers") -> dict[str, Any]:
    if video_check not in {"none", "headers", "full"}:
        raise ValueError("video_check 只能是 none、headers 或 full")
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
    if not str(info.get("robot_type", "")).strip():
        raise ValueError("meta/info.json 缺少非空 robot_type")
    fps = float(info.get("fps", 0))
    if not np.isfinite(fps) or fps <= 0:
        raise ValueError("meta/info.json 的 fps 必须为正数")
    for key in ("observation.state", "action"):
        if key not in features:
            raise ValueError(f"Missing required feature: {key}")
    camera_keys = sorted(key for key, feature in features.items() if feature.get("dtype") in {"image", "video"})
    parquet_files = sorted((root / "data").rglob("*.parquet"))
    if len(parquet_files) != len(episodes):
        raise ValueError(f"Parquet/episode mismatch: {len(parquet_files)} != {len(episodes)}")
    with futures.ProcessPoolExecutor(max_workers=workers) as executor:
        reports = []
        results = executor.map(_audit_parquet, parquet_files, [("observation.state", "action")] * len(parquet_files))
        for index, report in enumerate(results, start=1):
            reports.append(report)
            print(f"AUDITED PARQUET {index}/{len(parquet_files)}", flush=True)
    total_frames = sum(report["frames"] for report in reports)
    if total_frames != int(info.get("total_frames", -1)):
        raise ValueError(f"Frame total mismatch: {total_frames} != {info.get('total_frames')}")
    if len(episodes) != int(info.get("total_episodes", -1)):
        raise ValueError("Episode total in info.json is inconsistent")
    episode_indices = sorted(report["episode_index"] for report in reports)
    if episode_indices != list(range(len(episodes))):
        raise ValueError("Episode indices must be unique and contiguous from zero")
    dimensions = {key: sorted({report[f"{key}_dim"] for report in reports}) for key in ("observation.state", "action")}
    if any(len(values) != 1 for values in dimensions.values()):
        raise ValueError(f"Numeric dimensions differ between episodes: {dimensions}")
    for key, values in dimensions.items():
        declared_shape = features[key].get("shape")
        if declared_shape and list(declared_shape) != [values[0]]:
            raise ValueError(f"{key} metadata shape {declared_shape} != observed {[values[0]]}")
    known_tasks = {int(item["task_index"]): str(item["task"]) for item in tasks}
    task_frames: dict[str, int] = {}
    for report in reports:
        for raw_index, count in report["task_frames"].items():
            index = int(raw_index)
            if index not in known_tasks:
                raise ValueError(f"Unknown task_index {index} in {report['path']}")
            task_frames[known_tasks[index]] = task_frames.get(known_tasks[index], 0) + count
    video_keys = [key for key in camera_keys if features[key]["dtype"] == "video"]
    video_jobs = []
    frames_by_episode = {report["episode_index"]: report["frames"] for report in reports}
    for episode in episodes:
        episode_index = int(episode["episode_index"])
        expected_frames = frames_by_episode[episode_index]
        if int(episode.get("length", expected_frames)) != expected_frames:
            raise ValueError(f"episode {episode_index}: metadata length 与 Parquet 帧数不一致")
        for key in video_keys:
            shape = list(features[key].get("shape", []))
            if len(shape) != 3 or shape[2] != 3:
                raise ValueError(f"{key}: 视频 shape 必须为 [height, width, 3], 实际为 {shape}")
            video_jobs.append(
                (
                    _video_path(root, info, episode_index, key),
                    key,
                    expected_frames,
                    shape[0],
                    shape[1],
                    fps,
                    video_check,
                )
            )
    expected_paths = {job[0].resolve() for job in video_jobs}
    actual_paths = {path.resolve() for path in (root / "videos").rglob("*.mp4")} if video_keys else set()
    if actual_paths != expected_paths:
        missing = sorted(str(path) for path in expected_paths - actual_paths)
        extra = sorted(str(path) for path in actual_paths - expected_paths)
        raise ValueError(f"MP4 路径集合不一致: missing={missing[:5]}, extra={extra[:5]}")
    if video_check != "none" and video_jobs:
        with futures.ProcessPoolExecutor(max_workers=workers) as executor:
            for index, _ in enumerate(executor.map(_audit_video, video_jobs), start=1):
                print(f"AUDITED VIDEO {index}/{len(video_jobs)}", flush=True)
    return {
        "root": str(root),
        "robot_type": info.get("robot_type"),
        "episodes": len(episodes),
        "frames": total_frames,
        "tasks": len(tasks),
        "task_frames": task_frames,
        "numeric_dimensions": {key: values[0] for key, values in dimensions.items()},
        "fps": fps,
        "camera_keys": camera_keys,
        "video_files": len(actual_paths),
        "video_check": video_check,
        "workers": workers,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_root", type=pathlib.Path)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--video-check", choices=("none", "headers", "full"), default="headers")
    parser.add_argument("--report", type=pathlib.Path)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    report = audit_dataset(args.dataset_root.resolve(), args.workers, video_check=args.video_check)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    print("DATASET AUDIT PASS")


if __name__ == "__main__":
    main()
