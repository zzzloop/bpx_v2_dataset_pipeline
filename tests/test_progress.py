from bpx_v2_dataset_pipeline.server.progress import parse_progress_line


def test_parses_openpi_training_metrics() -> None:
    parsed = parse_progress_line(
        "Step 200: grad_norm=1.005, learning_rate=3.784e-06, loss=0.08145, update_norm=0.04274",
        total_units=1000,
    )
    assert parsed is not None
    assert parsed["current"] == 200
    assert parsed["percent"] == 20
    assert parsed["metrics"]["loss"] == 0.08145


def test_parses_tqdm_progress_with_carriage_return() -> None:
    parsed = parse_progress_line("\rComputing stats: 15%|██ | 120/800 [00:10<01:00]")
    assert parsed == {"kind": "progress", "current": 120, "total": 800, "percent": 15.0}


def test_parses_pipeline_counter() -> None:
    parsed = parse_progress_line("AUDITED VIDEO 3/12")
    assert parsed == {"kind": "progress", "current": 3, "total": 12, "percent": 25.0}
