from __future__ import annotations

import pathlib
import sys
import time

from bpx_v2_dataset_pipeline.server.commands import CommandSpec
from bpx_v2_dataset_pipeline.server.jobs import JobManager


def test_job_manager_persists_log_progress_and_success(tmp_path: pathlib.Path) -> None:
    manager = JobManager(tmp_path / "state")
    code = "print('Step 5: loss=0.25, grad_norm=1.5', flush=True)"
    job = manager.start("train", CommandSpec((sys.executable, "-c", code), tmp_path, total_units=10))
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = manager.get(job["id"])
        if job["status"] not in {"queued", "running", "cancelling"}:
            break
        time.sleep(0.05)
    assert job["status"] == "succeeded"
    assert "loss=0.25" in manager.tail(job["id"])
    assert manager.metrics(job["id"])[0]["metrics"]["grad_norm"] == 1.5
    assert JobManager(tmp_path / "state").get(job["id"])["status"] == "succeeded"
