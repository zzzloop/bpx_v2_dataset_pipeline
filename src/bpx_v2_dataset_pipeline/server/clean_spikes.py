from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import tempfile
from concurrent import futures
from typing import Any

import numpy as np

from bpx_v2_dataset_pipeline.server.audit import audit_dataset
from bpx_v2_dataset_pipeline.server.numeric_spikes import repair_isolated_spikes


def _load_thresholds(path: pathlib.Path) -> dict[str, dict[str, np.ndarray]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    output = {}
    for key in ("observation.state", "action"):
        if key not in raw:
            raise ValueError(f"Threshold config is missing {key}")
        output[key] = {
            "jump": np.asarray(raw[key]["jump_thresholds"], dtype=np.float64),
            "neighbor": np.asarray(raw[key]["neighbor_thresholds"], dtype=np.float64),
        }
    return output


def _clean_parquet(arguments: tuple[pathlib.Path, dict[str, dict[str, np.ndarray]], bool]) -> dict[str, Any]:
    path, thresholds, apply = arguments
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as error:
        raise RuntimeError("Install the server extra: uv sync --extra server") from error
    table = pq.read_table(path)
    counts = {}
    repairs = []
    output = table
    for key, config in thresholds.items():
        column_index = output.schema.get_field_index(key)
        if column_index < 0:
            raise ValueError(f"{path}: missing {key}")
        values = np.asarray(output[key].combine_chunks().to_pylist(), dtype=np.float32)
        result = repair_isolated_spikes(
            values,
            jump_thresholds=config["jump"],
            neighbor_thresholds=config["neighbor"],
        )
        counts[key] = result.count
        for frame_index, dimension in np.argwhere(result.mask):
            frame = int(frame_index)
            axis = int(dimension)
            repairs.append(
                {
                    "feature": key,
                    "frame_index": frame,
                    "dimension": axis,
                    "previous": float(values[frame - 1, axis]),
                    "original": float(values[frame, axis]),
                    "following": float(values[frame + 1, axis]),
                    "repaired": float(result.repaired[frame, axis]),
                }
            )
        if apply and result.count:
            field = output.schema.field(column_index)
            output = output.set_column(column_index, field, pa.array(result.repaired.tolist(), type=field.type))
    if apply and sum(counts.values()):
        with tempfile.NamedTemporaryFile(prefix=path.name, suffix=".tmp", dir=path.parent, delete=False) as handle:
            temporary_path = pathlib.Path(handle.name)
        try:
            pq.write_table(output, temporary_path)
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)
    return {"path": str(path), "counts": counts, "total": sum(counts.values()), "repairs": repairs}


def _copy_as_hardlinked_version(source: pathlib.Path, output: pathlib.Path) -> None:
    if output.exists():
        raise FileExistsError(f"Output exists: {output}")
    staging = output.with_name(f".{output.name}.partial")
    if staging.exists():
        raise FileExistsError(f"Staging output exists: {staging}")
    try:
        shutil.copytree(source, staging, copy_function=os.link)
        os.replace(staging, output)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_root", type=pathlib.Path)
    parser.add_argument("--thresholds", type=pathlib.Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--output-root", type=pathlib.Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=pathlib.Path, required=True)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    source = args.source_root.resolve()
    target = source
    if args.apply:
        if args.output_root is None:
            parser.error("--output-root is required with --apply")
        target = args.output_root.resolve()
        _copy_as_hardlinked_version(source, target)
    thresholds = _load_thresholds(args.thresholds)
    parquet_files = sorted((target / "data").rglob("*.parquet"))
    if not parquet_files:
        raise ValueError(f"数据集没有 Parquet episode: {target}")
    jobs = [(path, thresholds, args.apply) for path in parquet_files]
    with futures.ProcessPoolExecutor(max_workers=args.workers) as executor:
        results = []
        for index, result in enumerate(executor.map(_clean_parquet, jobs), start=1):
            results.append(result)
            print(f"SCANNED {index}/{len(jobs)}", flush=True)
    report = {
        "source": str(source),
        "output": str(target) if args.apply else None,
        "applied": args.apply,
        "episode_files": len(results),
        "repairs": sum(result["total"] for result in results),
        "files": results,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.apply:
        audit_dataset(target, args.workers)
    print(json.dumps({key: value for key, value in report.items() if key != "files"}, indent=2))
    print("SPIKE SCAN PASS" if not args.apply else "SPIKE CLEAN AND AUDIT PASS")


if __name__ == "__main__":
    main()
