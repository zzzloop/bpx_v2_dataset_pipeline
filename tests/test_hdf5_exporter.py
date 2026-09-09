from __future__ import annotations

import json
import pathlib

import numpy as np
import pytest

from bpx_v2_dataset_pipeline.server.audit import audit_dataset
from bpx_v2_dataset_pipeline.server.hdf5_exporter import export_hdf5

av = pytest.importorskip("av")
h5py = pytest.importorskip("h5py")
pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")


def _write_jsonl(path: pathlib.Path, records: list[dict]) -> None:
    path.write_text("".join(json.dumps(item) + "\n" for item in records), encoding="utf-8")


def _dataset(root: pathlib.Path) -> None:
    (root / "meta").mkdir(parents=True)
    (root / "data" / "chunk-000").mkdir(parents=True)
    video_dir = root / "videos" / "chunk-000" / "observation.images.eye"
    video_dir.mkdir(parents=True)
    info = {
        "robot_type": "bpx_v2_gripper",
        "fps": 30,
        "chunks_size": 1000,
        "total_episodes": 1,
        "total_frames": 3,
        "video_path": "videos/chunk-{episode_chunk:03d}/{video_key}/episode_{episode_index:06d}.mp4",
        "features": {
            "observation.state": {"dtype": "float32", "shape": [2]},
            "action": {"dtype": "float32", "shape": [2]},
            "observation.images.eye": {"dtype": "video", "shape": [16, 16, 3]},
        },
    }
    (root / "meta" / "info.json").write_text(json.dumps(info), encoding="utf-8")
    _write_jsonl(root / "meta" / "episodes.jsonl", [{"episode_index": 0, "length": 3}])
    _write_jsonl(root / "meta" / "tasks.jsonl", [{"task_index": 0, "task": "Move the block."}])
    table = pa.table(
        {
            "observation.state": [[0.0, 0.1], [0.2, 0.3], [0.4, 0.5]],
            "action": [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]],
            "episode_index": [0, 0, 0],
            "frame_index": [0, 1, 2],
            "timestamp": [0.0, 1 / 30, 2 / 30],
            "task_index": [0, 0, 0],
        }
    )
    pq.write_table(table, root / "data" / "chunk-000" / "episode_000000.parquet")
    container = av.open(str(video_dir / "episode_000000.mp4"), mode="w")
    stream = container.add_stream("libx264", rate=30)
    stream.width = 16
    stream.height = 16
    stream.pix_fmt = "yuv420p"
    for value in (20, 80, 140):
        frame = av.VideoFrame.from_ndarray(np.full((16, 16, 3), value, dtype=np.uint8), format="rgb24")
        for packet in stream.encode(frame):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()


def test_hdf5_export_is_derived_and_manifested(tmp_path: pathlib.Path) -> None:
    source = tmp_path / "lerobot"
    output = tmp_path / "hdf5"
    _dataset(source)
    manifest = export_hdf5(source, output, workers=1, compression="gzip", compression_level=1)
    assert manifest["total_frames"] == 3
    assert len(manifest["episodes"][0]["sha256"]) == 64
    with h5py.File(output / "episode_000000.hdf5", "r") as episode:
        assert episode["action"].shape == (3, 2)
        assert episode["observations/images/eye"].shape == (3, 16, 16, 3)
        assert json.loads(episode.attrs["task"]) == ["Move the block."]


def test_full_audit_decodes_video_and_checks_task_distribution(tmp_path: pathlib.Path) -> None:
    source = tmp_path / "lerobot"
    _dataset(source)
    report = audit_dataset(source, workers=1, video_check="full")
    assert report["video_check"] == "full"
    assert report["video_files"] == 1
    assert report["task_frames"] == {"Move the block.": 3}
