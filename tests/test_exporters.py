from pathlib import Path

import pytest

from bpx_v2_dataset_pipeline.server.exporters import DatasetExporter, ExporterRegistry, ExportRequest


class _RecorderExporter(DatasetExporter):
    def __init__(self, name: str = "hdf5") -> None:
        self._name = name
        self.requests: list[ExportRequest] = []

    @property
    def format_name(self) -> str:
        return self._name

    def export(self, request: ExportRequest) -> None:
        request.validate()
        self.requests.append(request)


def test_export_registry_is_explicit_and_rejects_duplicates(tmp_path: Path) -> None:
    exporter = _RecorderExporter()
    registry = ExporterRegistry([exporter])

    assert registry.names() == ("hdf5",)
    assert registry.get("HDF5") is exporter
    with pytest.raises(ValueError, match="already registered"):
        registry.register(_RecorderExporter())

    source = tmp_path / "canonical"
    source.mkdir()
    request = ExportRequest(source, tmp_path / "derived", "bpx_v2_gripper", "v001")
    registry.get("hdf5").export(request)
    assert exporter.requests == [request]


def test_export_request_cannot_target_canonical_dataset(tmp_path: Path) -> None:
    source = tmp_path / "canonical"
    source.mkdir()
    request = ExportRequest(source, source, "bpx_v2_gripper", "v001")

    with pytest.raises(ValueError, match="must not overwrite"):
        request.validate()
