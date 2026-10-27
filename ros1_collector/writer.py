"""Streaming LeRobot v2.1 writer for Python 3.8 / ROS Noetic.

Implements the pinned LeRobot v2.1 on-disk schema, not the newer v3 layout.
Only NumPy, Arrow and system ffmpeg are needed; no torch/LeRobot installation.
"""
import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import tempfile
import time

import numpy as np

from ros1_collector.contract import CAMERAS, JOINT_NAMES, MOTOR_NAMES, STREAMS
from ros1_collector.numbering import inherit_take_numbers, next_take_number, reserve_take_number

DATA_PATH = "data/chunk-{episode_chunk:03d}/episode_{episode_index:06d}.parquet"
VIDEO_PATH = "videos/chunk-{episode_chunk:03d}/{video_key}/episode_{episode_index:06d}.mp4"
SCALARS = {"timestamp": "float32", "frame_index": "int64", "episode_index": "int64",
           "index": "int64", "task_index": "int64", "bpx.real_timestamp": "float64"}


def atomic(path, value, lines=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        if lines:
            for row in value:
                stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
        else:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(str(temporary), str(path))


def load(path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def sha256(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def arrow_type(dtype):
    import pyarrow as pa
    return {"float32": pa.float32, "float64": pa.float64, "int64": pa.int64}[dtype]()


def check_save_dependencies():
    """Exercise the actual Arrow path BEFORE users spend time recording a take."""
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
        table = pa.table({"scalar": pa.array([0.], type=pa.float32()),
                          "vector": pa.array([[0., 1.]], type=pa.list_(pa.float32(), 2))})
        with tempfile.TemporaryDirectory(prefix="bpx-ros1-arrow-") as temporary:
            path = Path(temporary) / "check.parquet"
            pq.write_table(table, path)
            if not pq.ParquetFile(path).read().equals(table):
                raise RuntimeError("Parquet read-back mismatch")
        print("[PASS] Parquet save/read check: NumPy %s, PyArrow %s" % (np.__version__, pa.__version__), flush=True)
    except Exception as error:
        raise RuntimeError(
            "数采保存依赖自检失败，尚未开始录制。请只修复项目虚拟环境："
            ".venv-ros1/bin/python -m pip install --only-binary=:all: -r ros1_collector/requirements.txt; "
            "原始错误: " + str(error)
        ) from error


def features():
    result = {key: {"dtype": dtype, "shape": [1], "names": None} for key, dtype in SCALARS.items()}
    for key, names, dtype in (
        ("observation.state", JOINT_NAMES, "float32"), ("action", JOINT_NAMES, "float32"),
        ("bpx.hardware_state", MOTOR_NAMES[3:], "float32"),
        ("bpx.hardware_action", MOTOR_NAMES, "float32"),
        ("bpx.receive_time_ns", STREAMS, "int64"), ("bpx.source_time_ns", STREAMS, "int64"),
    ):
        result[key] = {"dtype": dtype, "shape": [len(names)], "names": list(names)}
    for key in CAMERAS:
        result["observation.images." + key] = {
            "dtype": "video", "shape": [360, 640, 3], "names": ["height", "width", "channels"],
            "info": {"video.height": 360, "video.width": 640, "video.fps": 30,
                     "video.channels": 3, "video.codec": "h264", "video.pix_fmt": "yuv420p",
                     "video.is_depth_map": False, "has_audio": False},
        }
    return result


class DatasetWriter:
    def __init__(self, root, config, *, numbering_source=None):
        import fcntl
        # Fail before recording, never download dependencies at runtime.
        check_save_dependencies()
        self.root, self.config = Path(root).resolve(), config
        self.schema = features()
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise RuntimeError("ffmpeg and ffprobe are required")
        encoders = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True,
                                  text=True, check=True, timeout=10).stdout
        if "libx264" not in encoders:
            raise RuntimeError("system ffmpeg needs the libx264 encoder")
        owner = self.root / ".bpx_v1_recorder.json"
        if self.root.exists() and any(self.root.iterdir()) and not owner.is_file():
            raise ValueError("Use a NEW output directory; existing datasets are never overwritten: " + str(self.root))
        self.root.mkdir(parents=True, exist_ok=True)
        self.file_lock = (self.root / ".collector.lock").open("a+")
        try:
            fcntl.flock(self.file_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.file_lock.close()
            raise RuntimeError("another recorder owns this dataset") from error
        identity = {"schema": "bpx-v1-ros1-effective18-video-4cam-v1", "features": self.schema, "fps": 30}
        if owner.exists() and load(owner) != identity:
            raise ValueError("数据集格式不同，不能把四路数据追加进三路目录；请使用新的 *_4cam 输出目录，旧数据不要删除")
        atomic(owner, identity)
        self.pending = self.root / ".bpx_pending"
        self.commits = self.root / ".bpx_commits"
        self.takes = self.root / "takes"
        self.pending.mkdir(exist_ok=True)
        self.commits.mkdir(exist_ok=True)
        self.takes.mkdir(exist_ok=True)
        if numbering_source is not None:
            inherit_take_numbers(self.root, numbering_source)
        self.active = None
        # A completed transaction can be recovered; incomplete takes remain inspectable.
        for descriptor in sorted(self.pending.glob("*/commit.json"), key=lambda path: load(path)["episode_index"]):
            self._publish(descriptor.parent, load(descriptor))
        self._metadata()

    def _records(self):
        records = [load(path) for path in sorted(self.commits.glob("*.json"))]
        if [row["episode_index"] for row in records] != list(range(len(records))):
            raise ValueError("non-contiguous committed episode ledger; inspect dataset before appending")
        return records

    def _metadata(self):
        records = self._records()
        tasks = []
        for row in records:
            if row["task"] not in tasks:
                tasks.append(row["task"])
        atomic(self.root / "meta/tasks.jsonl", [dict(task_index=i, task=task) for i, task in enumerate(tasks)], lines=True)
        atomic(self.root / "meta/episodes.jsonl", [
            dict(episode_index=row["episode_index"], tasks=[row["task"]], length=row["frames"]) for row in records
        ], lines=True)
        atomic(self.root / "meta/episodes_stats.jsonl", [
            dict(episode_index=row["episode_index"], stats=row["stats"]) for row in records
        ], lines=True)
        atomic(self.root / "meta/bpx_capture.jsonl", [{key: value for key, value in row.items()
            if key not in ("stats", "files")} for row in records], lines=True)
        info = dict(codebase_version="v2.1", robot_type="bpx_v1", total_episodes=len(records),
                    total_frames=sum(row["frames"] for row in records), total_tasks=len(tasks),
                    total_videos=len(records) * len(CAMERAS), total_chunks=(len(records) + 999) // 1000,
                    chunks_size=1000, fps=30, splits={"train": "0:%d" % len(records)},
                    data_path=DATA_PATH, video_path=VIDEO_PATH, features=self.schema)
        # Publish info LAST. Do not train against a dataset that is still being recorded.
        atomic(self.root / "meta/info.json", info)
        self.episodes, self.total_frames, self.tasks = len(records), info["total_frames"], tasks

    def begin(self, task):
        if self.active is not None:
            raise RuntimeError("an episode is already active")
        number = reserve_take_number(self.root)
        take_dir = self.takes / str(number)
        take_dir.mkdir()
        atomic(take_dir / "recording.json", {"take_number": number, "state": "recording", "task": task})
        stage = self.pending / str(number)
        stage.mkdir()
        atomic(stage / "take.json", {"id": stage.name, "take_number": number, "task": task, "created_at": time.time()})
        self.active = {"stage": stage, "take_number": number, "task": task, "processes": {}, "logs": {}, "frames": 0,
                       "image_hist": {key: np.zeros((3, 256), dtype=np.int64) for key in CAMERAS},
                       "sampled_images": 0, "first_ns": None, "last_ns": None, "max_gap_ms": 0.}
        try:
            self.active["journal"] = (stage / "frames.jsonl").open("w", encoding="utf-8")
            for key in CAMERAS:
                log = (stage / (key + ".log")).open("wb")
                self.active["logs"][key] = log
                process = subprocess.Popen([
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
                    "-f", "rawvideo", "-pixel_format", "rgb24", "-video_size", "640x360",
                    "-framerate", "30", "-i", "pipe:0", "-an", "-c:v", "libx264",
                    "-preset", "ultrafast", "-crf", "18", "-pix_fmt", "yuv420p", "-threads", "2",
                    "-movflags", "+faststart", str(stage / (key + ".mp4")),
                ], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log)
                os.set_blocking(process.stdin.fileno(), False)
                self.active["processes"][key] = process
        except BaseException:
            self.abort()
            raise

    def add(self, frame):
        take = self.active
        if take is None:
            raise RuntimeError("no episode is active")
        timestamp = frame["capture_ns"]
        if take["first_ns"] is None:
            take["first_ns"] = timestamp
        if take["last_ns"] is not None:
            gap = (timestamp - take["last_ns"]) / 1e6
            take["max_gap_ms"] = max(take["max_gap_ms"], gap)
            if gap <= 0 or gap > self.config["max_frame_gap_ms"]:
                raise RuntimeError("capture gap %.1f ms; this take cannot be saved as normal 30 Hz data" % gap)
        sample_stats = take["frames"] % 30 == 0
        for key in CAMERAS:
            rgb = frame["images"][key]
            if rgb.shape != (360, 640, 3) or rgb.dtype != np.uint8:
                raise ValueError("invalid RGB frame: " + key)
            remaining = memoryview(rgb).cast("B")
            process = take["processes"][key]
            deadline = time.monotonic() + 5
            while remaining:
                timeout = deadline - time.monotonic()
                if timeout <= 0 or not select.select([], [process.stdin], [], timeout)[1]:
                    raise TimeoutError("MP4 encoder blocked: " + key)
                try:
                    count = os.write(process.stdin.fileno(), remaining)
                    if count <= 0:
                        raise BrokenPipeError("MP4 encoder stopped: " + key)
                    remaining = remaining[count:]
                except BlockingIOError:
                    continue
            if sample_stats:
                for channel in range(3):
                    take["image_hist"][key][channel] += np.bincount(rgb[:, :, channel].ravel(), minlength=256)
        record = {key: np.asarray(frame[key]).tolist() for key in self.schema if key not in SCALARS
                  and self.schema[key]["dtype"] != "video" and key != "bpx.real_timestamp"}
        record["bpx.real_timestamp"] = (timestamp - take["first_ns"]) / 1e9
        take["journal"].write(json.dumps(record, allow_nan=False) + "\n")
        take["frames"] += 1
        take["sampled_images"] += int(sample_stats)
        take["last_ns"] = timestamp
        if take["frames"] % 30 == 0:
            take["journal"].flush()
            os.fsync(take["journal"].fileno())

    def _close_encoders(self):
        take = self.active
        if take.get("journal") is not None and not take["journal"].closed:
            take["journal"].flush()
            os.fsync(take["journal"].fileno())
            take["journal"].close()
        for process in take["processes"].values():
            if not process.stdin.closed:
                process.stdin.close()
        for key, process in take["processes"].items():
            if process.wait(timeout=15) != 0:
                raise RuntimeError("MP4 encoding failed: " + key)
        for log in take["logs"].values():
            if not log.closed:
                log.close()

    def finish(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        take = self.active
        self._close_encoders()
        n = take["frames"]
        if n < 2:
            raise ValueError("need at least two frames")
        effective_fps = (n - 1) * 1e9 / (take["last_ns"] - take["first_ns"])
        if not self.config["minimum_effective_fps"] <= effective_fps <= self.config["maximum_effective_fps"]:
            raise ValueError("actual FPS %.2f outside allowed near-30-Hz range" % effective_fps)
        for key in CAMERAS:
            probe = json.loads(subprocess.run([
                "ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries",
                "stream=nb_read_frames,width,height,avg_frame_rate", "-of", "json",
                str(take["stage"] / (key + ".mp4")),
            ], check=True, capture_output=True, text=True, timeout=60).stdout)["streams"][0]
            if (int(probe["nb_read_frames"]), probe["width"], probe["height"]) != (n, 640, 360):
                raise ValueError("video/frame count mismatch: " + key)
            numerator, denominator = map(int, probe["avg_frame_rate"].split("/"))
            if numerator != 30 * denominator:
                raise ValueError("MP4 FPS is not 30: " + key)
        rows = [json.loads(line) for line in (take["stage"] / "frames.jsonl").read_text().splitlines()]
        if len(rows) != n:
            raise ValueError("numeric/frame count mismatch")
        task_index = self.tasks.index(take["task"]) if take["task"] in self.tasks else len(self.tasks)
        numeric = {"timestamp": np.arange(n, dtype=np.float32) / 30,
                   "frame_index": np.arange(n, dtype=np.int64),
                   "episode_index": np.full(n, self.episodes, dtype=np.int64),
                   "index": np.arange(self.total_frames, self.total_frames + n, dtype=np.int64),
                   "task_index": np.full(n, task_index, dtype=np.int64),
                   "bpx.real_timestamp": np.asarray([row["bpx.real_timestamp"] for row in rows], dtype=np.float64)}
        numeric.update({key: np.asarray([row[key] for row in rows], dtype=ft["dtype"])
                        for key, ft in self.schema.items() if key not in SCALARS and ft["dtype"] != "video"})
        stats, columns, hf_features = {}, {}, {}
        for key, value in numeric.items():
            if not np.isfinite(value).all():
                raise ValueError("non-finite data: " + key)
            scalar = key in SCALARS
            dtype = self.schema[key]["dtype"]
            stats[key] = {name: getattr(np, name)(value, axis=0, keepdims=scalar).tolist()
                          for name in ("min", "max", "mean", "std")}
            stats[key]["count"] = [n]
            value_feature = {"dtype": dtype, "_type": "Value"}
            hf_features[key] = value_feature if scalar else {
                "feature": value_feature, "length": self.schema[key]["shape"][0], "_type": "Sequence"}
            columns[key] = pa.array(value.tolist(), type=arrow_type(dtype) if scalar else
                                    pa.list_(arrow_type(dtype), self.schema[key]["shape"][0]))
        table = pa.table(columns).replace_schema_metadata({b"huggingface": json.dumps({
            "info": {"features": hf_features}}).encode()})
        parquet = take["stage"] / "episode.parquet"
        pq.write_table(table, parquet, compression="snappy")
        if not pq.ParquetFile(parquet).read().equals(table):
            raise ValueError("Parquet read-back differs from captured data")
        for key, histogram in take["image_hist"].items():
            values = np.arange(256, dtype=np.float64) / 255.
            count = histogram.sum(axis=1)
            mean = (histogram * values).sum(axis=1) / count
            variance = np.maximum(0, (histogram * values**2).sum(axis=1) / count - mean**2)
            stats["observation.images." + key] = {
                "min": (np.argmax(histogram > 0, axis=1) / 255.).reshape(3, 1, 1).tolist(),
                "max": ((255 - np.argmax((histogram > 0)[:, ::-1], axis=1)) / 255.).reshape(3, 1, 1).tolist(),
                "mean": mean.reshape(3, 1, 1).tolist(), "std": np.sqrt(variance).reshape(3, 1, 1).tolist(),
                "count": [take["sampled_images"]],
            }
        layout = {"episode_chunk": self.episodes // 1000, "episode_index": self.episodes}
        files = [{"source": "episode.parquet", "target": DATA_PATH.format(**layout), "sha256": sha256(parquet)}]
        for key in CAMERAS:
            files.append({"source": key + ".mp4", "target": VIDEO_PATH.format(video_key="observation.images." + key, **layout),
                          "sha256": sha256(take["stage"] / (key + ".mp4"))})
        record = {"episode_index": self.episodes, "attempt_id": take["stage"].name,
                  "take_number": take["take_number"], "task": take["task"],
                  "frames": n, "effective_fps": effective_fps, "max_frame_gap_ms": take["max_gap_ms"],
                  "config": self.config, "stats": stats, "files": files, "saved_at": time.time(),
                  "warning": "" if 28 <= effective_fps <= 32 else "Frame rate differs noticeably from nominal 30 Hz",
                  "image_stats": "RGB channel statistics sampled every 30 captured frames; not OpenPI norm stats"}
        atomic(take["stage"] / "commit.json", record)
        self._publish(take["stage"], record)
        self.active = None
        self._metadata()
        return {key: value for key, value in record.items() if key not in ("stats", "files", "config")}

    def _publish(self, stage, record):
        # Idempotent recovery only of a fully verified transaction.
        if stage.resolve().parent != self.pending.resolve() or load(stage / "take.json")["id"] != stage.name:
            raise ValueError("unowned transaction directory")
        existing = self._records()
        index = record["episode_index"]
        if type(index) is not int or index < 0:
            raise ValueError("invalid transaction episode index")
        layout = {"episode_index": index, "episode_chunk": index // 1000}
        expected = {"episode.parquet": DATA_PATH.format(**layout)}
        expected.update({key + ".mp4": VIDEO_PATH.format(video_key="observation.images." + key, **layout)
                         for key in CAMERAS})
        if (len(record["files"]) != len(expected)
                or {item["source"]: item["target"] for item in record["files"]} != expected):
            raise ValueError("transaction artifact paths differ from the fixed episode layout")
        ledger = self.commits / ("%06d.json" % index)
        if index > len(existing) or (ledger.exists() and load(ledger) != record):
            raise ValueError("conflicting episode transaction; originals unchanged")
        for item in record["files"]:
            source, destination = stage / item["source"], self.root / item["target"]
            if source.resolve().parent != stage.resolve() or self.root not in destination.resolve().parents:
                raise ValueError("unsafe artifact path")
            check = destination if destination.exists() else source
            if sha256(check) != item["sha256"]:
                raise ValueError("artifact checksum mismatch: " + str(check))
            if not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(str(source), str(destination))
        atomic(ledger, record)
        if record.get("take_number") is not None:
            number = record["take_number"]
            if type(number) is not int or number < 0:
                raise ValueError("invalid human recording number")
            directory = self.takes / str(number)
            directory.mkdir(exist_ok=True)
            marker = directory / "recording.json"
            if marker.exists() and load(marker).get("take_number") != number:
                raise ValueError("human recording folder belongs to a different take")
            links = {}
            for item in record["files"]:
                name = "data.parquet" if item["source"] == "episode.parquet" else item["source"]
                destination, source = directory / name, self.root / item["target"]
                if destination.exists():
                    if not os.path.samefile(str(source), str(destination)):
                        raise FileExistsError("refusing to overwrite recording view: " + str(destination))
                else:
                    os.link(str(source), str(destination))
                links[name] = item["target"]
            atomic(marker, {"take_number": number, "state": "saved", "episode_index": index,
                            "task": record["task"], "frames": record["frames"], "files": links})
        shutil.rmtree(stage)  # Exact owned pending take only; never a dataset or source directory.

    def mark_error(self, error):
        if self.active is not None:
            number = self.active["take_number"]
            atomic(self.takes / str(number) / "recording.json", {
                "take_number": number, "state": "error", "error": str(error),
                "task": self.active["task"], "frames": self.active["frames"],
                "pending": str(self.active["stage"]),
            })

    def _terminate_encoders(self):
        if self.active is None:
            return
        take = self.active
        for process in take["processes"].values():
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
        for stream in [take.get("journal"), *take["logs"].values()]:
            if stream and not stream.closed:
                stream.close()

    def abort(self):
        if self.active is None:
            return
        self._terminate_encoders()
        take = self.active
        stage = take["stage"]
        if (stage.resolve().parent != self.pending.resolve()
                or load(stage / "take.json")["id"] != stage.name):
            raise ValueError("refusing to discard an unowned directory")
        if (stage / "commit.json").exists():
            raise RuntimeError("save transaction began; restart to recover it, do not discard")
        number = take["take_number"]
        atomic(self.takes / str(number) / "recording.json", {"take_number": number, "state": "discarded",
               "task": take["task"], "frames": take["frames"]})
        shutil.rmtree(stage)
        self.active = None

    def close(self):
        try:
            if self.active is not None:
                # Preserve failed takes on shutdown; only an explicit discard removes them.
                try:
                    self._close_encoders()
                except Exception:
                    self._terminate_encoders()
        finally:
            self.file_lock.close()

    def numbering(self):
        return {"take_number": self.active["take_number"] if self.active is not None else None,
                "next_take_number": next_take_number(self.root), "takes_dir": str(self.takes)}
