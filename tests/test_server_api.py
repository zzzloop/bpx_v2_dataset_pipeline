from __future__ import annotations

import pathlib

from fastapi.testclient import TestClient

from bpx_v2_dataset_pipeline.server.api import create_app


def test_server_dashboard_requires_token_and_exposes_defaults(tmp_path: pathlib.Path) -> None:
    app = create_app(state_dir=tmp_path / "state", default_openpi_root=tmp_path / "openpi")
    client = TestClient(app)
    assert client.get("/").status_code == 401
    token = (tmp_path / "state" / ".server-token").read_text(encoding="utf-8").strip()
    response = client.get("/api/config", headers={"X-BPX-Token": token})
    assert response.status_code == 200
    assert response.json()["default_workers"] == 32
    assert response.json()["default_openpi_root"] == str(tmp_path / "openpi")
