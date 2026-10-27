"""Minimal, subscriber-only ROS1 collector; Python 3.8+, no ROS2 imports."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit

from ros1_collector.contract import validate_config
from ros1_collector.source import Ros1Source
from ros1_collector.writer import DatasetWriter

PROJECT = Path(__file__).resolve().parent.parent


class Recorder:
    def __init__(self, source, writer, config):
        self.source, self.writer, self.config = source, writer, config
        self.lock = threading.Lock()
        self.stop_event, self.discard_event = threading.Event(), threading.Event()
        self.state, self.error, self.last = "idle", "", None
        self.worker = None
        self.frames, self.started, self.last_capture = 0, 0., None
        self.first_capture = None

    def start(self, task):
        task = str(task).strip()
        if not task or len(task) > 256:
            raise ValueError("请填写1–256字符的任务指令，建议英文")
        with self.lock:
            if self.state != "idle":
                raise ValueError("上一条录制尚未结束；异常时请先丢弃本条")
            health = self.source.health()
            if not health["ready"]:
                raise ValueError("输入未就绪: " + json.dumps(health, ensure_ascii=False))
            self.state, self.error = "starting", ""
        try:
            self.writer.begin(task)
            self.source.reset()
            self.stop_event.clear()
            self.discard_event.clear()
            with self.lock:
                self.frames, self.started = 0, time.monotonic()
                self.first_capture, self.last_capture = None, None
                self.state = "recording"
                self.worker = threading.Thread(target=self._record, name="ros1-video-writer", daemon=False)
                self.worker.start()
        except Exception as error:
            with self.lock:
                self.state, self.error = "error", str(error)
            raise

    def stop(self, discard=False):
        with self.lock:
            if self.state == "recording":
                if discard:
                    self.discard_event.set()
                self.state = "discarding" if discard else "saving"
                self.stop_event.set()  # Stop acquiring FIRST; encoding/checks finish asynchronously.
            elif self.state == "error" and discard:
                if self.worker is not None and self.worker.is_alive():
                    raise ValueError("正在关闭异常录制，请稍后重试丢弃")
                self.state = "discarding"
                self.worker = threading.Thread(target=self._discard, daemon=False)
                self.worker.start()
            elif self.state in ("saving", "discarding"):
                return
            else:
                raise ValueError("当前没有可停止的录制")

    def _discard(self):
        try:
            number = self.writer.active["take_number"] if self.writer.active is not None else None
            self.writer.abort()
            with self.lock:
                self.state, self.error = "idle", ""
                self.last = {"discarded": True, "take_number": number, "frames": self.frames,
                             "message": "本条未保存的临时数据已删除，已保存的 episode 不受影响"}
        except Exception as error:
            with self.lock:
                self.state, self.error = "error", str(error)

    def retry(self):
        with self.lock:
            if self.state != "error" or (self.worker is not None and self.worker.is_alive()):
                raise ValueError("仅可在异常录制已停止后重试保存")
            if self.writer.active is None:
                raise ValueError("没有可重试的缓存数据")
            if (self.writer.active["stage"] / "commit.json").exists():
                raise ValueError("保存事务已生成，请重启采集程序自动恢复；不要丢弃该目录")
            self.state, self.error = "saving", ""
            self.worker = threading.Thread(target=self._retry_save, name="ros1-save-retry", daemon=False)
            self.worker.start()

    def _retry_save(self):
        try:
            result = self.writer.finish()
            with self.lock:
                self.last, self.state = result, "idle"
        except Exception as error:
            logging.exception("ROS1 recording save retry failed")
            with self.lock:
                self.error, self.state = str(error), "error"
            try:
                self.writer.mark_error(error)
            except Exception:
                logging.exception("Could not persist the recording error marker")

    def _record(self):
        deadline, last_good = time.monotonic(), time.monotonic()
        try:
            while not self.stop_event.is_set():
                if self.stop_event.wait(max(0., deadline - time.monotonic())):
                    break
                frame = self.source.sample()
                if frame is None:
                    if time.monotonic() - last_good > self.config["max_frame_gap_ms"] / 1000:
                        raise RuntimeError("同步输入中断或相机缺帧；只停止数采，不影响机器人。请检查话题后丢弃重录")
                    self.stop_event.wait(.003)
                    continue
                self.writer.add(frame)
                with self.lock:
                    self.frames += 1
                    if self.first_capture is None:
                        self.first_capture = frame["capture_ns"]
                    self.last_capture = frame["capture_ns"]
                last_good = time.monotonic()
                deadline += 1. / self.config["fps"]
                if deadline < last_good - 1. / self.config["fps"]:
                    deadline = last_good
            if self.discard_event.is_set():
                self._discard()
                return
            result = self.writer.finish()
            with self.lock:
                self.last, self.state = result, "idle"
        except Exception as error:
            # Keep incomplete files inspectable, never publish bad data as a training episode.
            self.stop_event.set()
            logging.exception("ROS1 recording/capture finalization failed; pending data retained")
            with self.lock:
                self.error, self.state = str(error), "error"
            if self.writer.active is not None:
                try:
                    self.writer._close_encoders()
                except Exception:
                    # The UI offers bounded termination/discard, without touching hardware.
                    pass
                self.writer.mark_error(error)

    def status(self):
        with self.lock:
            actual = None
            if self.frames > 1 and self.last_capture != self.first_capture:
                actual = (self.frames - 1) * 1e9 / (self.last_capture - self.first_capture)
            return {"state": self.state, "error": self.error, "frames": self.frames,
                    "elapsed_sec": time.monotonic() - self.started if self.state == "recording" else 0,
                    "effective_fps": actual, "target_fps": 30, "resolution": "640×360",
                    "health": self.source.health(), "output_dir": str(self.writer.root),
                    "saved_episodes": self.writer.episodes, "last": self.last, **self.writer.numbering()}

    def close(self):
        if self.state == "recording":
            self.stop(discard=True)
        if self.worker is not None:
            self.worker.join(timeout=2)
            if self.worker.is_alive():
                print("正在完成当前文件关闭/保存，请等待；不要强制结束。", flush=True)
                self.worker.join()
        self.writer.close()
        self.source.close()


def handler(recorder):
    page = Path(__file__).with_name("index.html").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, value, content_type="application/json; charset=utf-8"):
            body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def local_request(self):
            host = self.headers.get("Host", "")
            if urlsplit("//" + host).hostname not in ("127.0.0.1", "localhost", "::1"):
                return False
            origin = self.headers.get("Origin")
            return not origin or origin == "http://" + host

        def do_GET(self):
            if not self.local_request():
                return self.reply(403, {"error": "仅允许本机或SSH转发访问"})
            path = urlsplit(self.path).path
            if path == "/":
                return self.reply(200, page, "text/html; charset=utf-8")
            if path == "/api/state":
                return self.reply(200, recorder.status())
            self.reply(404, {"error": "not found"})

        def do_POST(self):
            if not self.local_request() or self.headers.get("X-BPX-Collector") != "1":
                return self.reply(403, {"error": "需要同源采集页面请求"})
            try:
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= 4096:
                    raise ValueError("invalid request length")
                data = json.loads(self.rfile.read(length))
                if self.path == "/api/start":
                    recorder.start(data.get("task", ""))
                elif self.path == "/api/stop":
                    recorder.stop()
                elif self.path == "/api/discard":
                    recorder.stop(discard=True)
                elif self.path == "/api/retry":
                    recorder.retry()
                else:
                    return self.reply(404, {"error": "not found"})
                self.reply(202, recorder.status())
            except Exception as error:
                self.reply(400, {"error": str(error)})

        def log_message(self, template, *args):
            if args and str(args[0]).startswith("GET /api/state"):
                return
            super().log_message(template, *args)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    validate_config(config)
    output = args.output_dir or Path(config["output_dir"])
    if not output.is_absolute():
        output = PROJECT / output
    numbering_source = None
    if args.output_dir is None and config.get("numbering_source_dir"):
        numbering_source = Path(config["numbering_source_dir"])
        if not numbering_source.is_absolute():
            numbering_source = PROJECT / numbering_source
    source = Ros1Source(config)
    writer = DatasetWriter(output, config, numbering_source=numbering_source)
    recorder = Recorder(source, writer, config)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(recorder))
    server.daemon_threads = True
    try:
        source.start()
        print("ROS1 LeRobot collector: http://127.0.0.1:%d" % args.port, flush=True)
        print("Output: %s | 4 cameras, 640x360, target 30 Hz | NO hardware publishers" % output, flush=True)
        server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        recorder.close()


if __name__ == "__main__":
    main()
