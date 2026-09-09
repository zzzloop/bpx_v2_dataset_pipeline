from __future__ import annotations

import argparse
import asyncio
import dataclasses
import pathlib
import uuid

from pydantic import BaseModel

from bpx_v2_dataset_pipeline.collector.catalog import DEFAULT_LAYOUTS, DEFAULT_OPERATORS, TASK_PRESETS
from bpx_v2_dataset_pipeline.collector.mock_backend import MockCaptureBackend
from bpx_v2_dataset_pipeline.collector.service import CollectorService
from bpx_v2_dataset_pipeline.collector.translator import TaskTranslator
from bpx_v2_dataset_pipeline.models import AttemptMetadata, AttemptStatus
from bpx_v2_dataset_pipeline.session_store import SessionStore


class StartRequest(BaseModel):
    task_en: str
    task_zh: str = ""
    operator_id: str
    layout_id: str
    embodiment: str
    note: str = ""
    session_id: str = ""


class FinishRequest(BaseModel):
    status: str
    failure_reason: str = ""
    note: str = ""


class TranslateRequest(BaseModel):
    chinese: str


class FailureReasonRequest(BaseModel):
    attempt_id: int
    failure_reason: str = ""


def create_app(*, state_dir: pathlib.Path, recordings_dir: pathlib.Path, mock: bool):
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as error:
        raise RuntimeError("Install the collector extra: uv sync --extra collector") from error
    if not mock:
        raise RuntimeError("ROS2 backend is intentionally disabled until the hardware data contract is frozen")

    store = SessionStore(state_dir / "collector.sqlite3")
    store.recover_interrupted()
    service = CollectorService(store, MockCaptureBackend(), recordings_dir)
    project_root = pathlib.Path(__file__).resolve().parents[3]
    translator = TaskTranslator.from_project(project_root)
    web_root = project_root / "web"
    app = FastAPI(title="BPX v2 Dataset Collector")

    @app.get("/")
    async def index():
        return FileResponse(web_root / "index.html")

    @app.get("/api/status")
    async def status():
        return service.status()

    @app.get("/api/catalog")
    async def catalog():
        operators = list(dict.fromkeys([*store.distinct_values("operator_id"), *DEFAULT_OPERATORS]))
        layouts = list(dict.fromkeys([*store.distinct_values("layout_id"), *DEFAULT_LAYOUTS]))
        return {
            "tasks": [
                {"id": item.id, "category": item.category, "zh": item.zh, "en": item.en} for item in TASK_PRESETS
            ],
            "operators": operators,
            "layouts": layouts,
            "translator": dataclasses.asdict(translator.info),
        }

    @app.post("/api/translate")
    async def translate(request: TranslateRequest):
        try:
            result = await asyncio.to_thread(translator.translate, request.chinese)
            return {
                "english": result.english,
                "source": result.source,
                "confidence": result.confidence,
            }
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.post("/api/attempts/start")
    async def start(request: StartRequest):
        try:
            metadata = AttemptMetadata(
                session_id=request.session_id.strip() or str(uuid.uuid4()),
                task_en=request.task_en,
                task_zh=request.task_zh,
                operator_id=request.operator_id,
                layout_id=request.layout_id,
                embodiment=request.embodiment,
                note=request.note,
            )
            active = await service.start(metadata)
            return {"attempt_id": active.attempt_id}
        except (RuntimeError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/api/attempts/finish")
    async def finish(request: FinishRequest):
        try:
            return await service.finish(
                AttemptStatus(request.status),
                failure_reason=request.failure_reason,
                note=request.note,
            )
        except (RuntimeError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/api/attempts/failure-reason")
    async def update_failure_reason(request: FailureReasonRequest):
        try:
            return store.update_failure_reason(request.attempt_id, request.failure_reason)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    app.mount("/static", StaticFiles(directory=web_root), name="static")
    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true", help="Run without ROS2 or hardware output")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--state-dir", type=pathlib.Path, default=pathlib.Path("state"))
    parser.add_argument(
        "--recordings-dir",
        type=pathlib.Path,
        default=pathlib.Path("recordings/lerobot/bpx_v2_humanoid_raw"),
    )
    args = parser.parse_args()
    import uvicorn

    app = create_app(state_dir=args.state_dir, recordings_dir=args.recordings_dir, mock=args.mock)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
