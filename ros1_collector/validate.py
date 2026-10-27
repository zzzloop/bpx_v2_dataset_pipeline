"""Run on the TRAINING SERVER with its pinned LeRobot v2.1 environment."""
import argparse
import json
from pathlib import Path

import numpy as np

from ros1_collector.contract import CAMERAS, JOINT_NAMES


def validate(root):
    import pyarrow.parquet as pq
    from lerobot.common.datasets.lerobot_dataset import CODEBASE_VERSION, LeRobotDataset

    if CODEBASE_VERSION != "v2.1":
        raise ValueError("use the existing OpenPI-pinned LeRobot v2.1 environment")
    root = Path(root).resolve()
    info = json.loads((root / "meta/info.json").read_text(encoding="utf-8"))
    assert info["codebase_version"] == "v2.1" and info["fps"] == 30
    assert info["robot_type"] == "bpx_v1" and info["total_episodes"] > 0
    for key in ("observation.state", "action"):
        assert info["features"][key]["shape"] == [18]
        assert info["features"][key]["names"] == JOINT_NAMES
    # Keep the server validator useful for both historical 3-camera and new 4-camera data.
    cameras = [camera for camera in CAMERAS if "observation.images." + camera in info["features"]]
    assert set(CAMERAS[:3]).issubset(cameras)
    assert info["total_videos"] == info["total_episodes"] * len(cameras)
    for camera in cameras:
        feature = info["features"]["observation.images." + camera]
        assert feature["dtype"] == "video" and feature["shape"] == [360, 640, 3]
    repo_id = "bpx/bpx_v1_humanoid_raw_4cam" if "right_eye" in cameras else "bpx/bpx_v1_humanoid_raw"
    dataset = LeRobotDataset(repo_id, root=root, download_videos=False)
    rows = [json.loads(line) for line in (root / "meta/episodes.jsonl").read_text().splitlines()]
    captures = [json.loads(line) for line in (root / "meta/bpx_capture.jsonl").read_text().splitlines()]
    offset, sampled = 0, 0
    assert len(rows) == len(captures) == info["total_episodes"]
    for index, episode in enumerate(rows):
        assert episode["episode_index"] == index
        length = episode["length"]
        values = dict(episode_index=index, episode_chunk=index // info["chunks_size"])
        table = pq.read_table(root / info["data_path"].format(**values))
        assert table.num_rows == length
        for key in ("observation.state", "action"):
            matrix = np.asarray(table[key].to_pylist(), dtype=np.float32)
            assert matrix.shape == (length, 18) and np.isfinite(matrix).all()
        assert np.array_equal(np.asarray(table["index"]), np.arange(offset, offset + length))
        assert np.allclose(np.asarray(table["timestamp"]), np.arange(length) / 30, atol=1e-4)
        real = np.asarray(table["bpx.real_timestamp"].to_pylist()).ravel()
        assert np.all(np.diff(real) > 0)
        capture = captures[index]
        assert np.isclose((length - 1) / real[-1], capture["effective_fps"])
        assert capture["config"]["minimum_effective_fps"] <= capture["effective_fps"] <= capture["config"]["maximum_effective_fps"]
        for frame in sorted({0, length // 2, length - 1}):
            item = dataset[offset + frame]  # Actual LeRobot video decoding, not just our own metadata reader.
            for camera in cameras:
                image = item["observation.images." + camera]
                assert tuple(image.shape) == (3, 360, 640) and bool(image.isfinite().all())
            for key in ("observation.state", "action"):
                np.testing.assert_array_equal(item[key].numpy(), np.asarray(table[key][frame].as_py(), dtype=np.float32))
            assert dataset.meta.tasks[int(item["task_index"].item())] in episode["tasks"]
            sampled += 1
        offset += length
        print("VALIDATED %d/%d: frames=%d actual=%.2f Hz" % (index + 1, len(rows), length, capture["effective_fps"]), flush=True)
    assert offset == len(dataset) == info["total_frames"]
    print("LEROBOT V2.1 READ/VIDEO PASS: episodes=%d frames=%d sampled_frames=%d" % (len(rows), offset, sampled), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    validate(parser.parse_args().dataset)


if __name__ == "__main__":
    main()
