"""Stable plugin boundary for derived dataset exports.

The canonical dataset remains LeRobot. Exporters may create disposable HDF5 or
other derived representations, but they must never mutate the source dataset.
"""

from __future__ import annotations

import abc
import dataclasses
from collections.abc import Iterable
from pathlib import Path


@dataclasses.dataclass(frozen=True)
class ExportRequest:
    """Immutable inputs supplied to a dataset exporter."""

    source_root: Path
    output_root: Path
    robot_type: str
    dataset_version: str

    def validate(self) -> None:
        if not self.source_root.is_dir():
            raise ValueError(f"LeRobot source does not exist: {self.source_root}")
        if self.source_root.resolve() == self.output_root.resolve():
            raise ValueError("Export output must not overwrite the canonical LeRobot source")
        if not self.robot_type.strip():
            raise ValueError("robot_type must not be empty")
        if not self.dataset_version.strip():
            raise ValueError("dataset_version must not be empty")


class DatasetExporter(abc.ABC):
    """Interface implemented by optional derived-format exporters."""

    @property
    @abc.abstractmethod
    def format_name(self) -> str:
        """Return the unique CLI/config name of this export format."""

    @abc.abstractmethod
    def export(self, request: ExportRequest) -> None:
        """Write a derived dataset without modifying ``request.source_root``."""


class ExporterRegistry:
    """Small explicit registry; importing a plugin never runs an export."""

    def __init__(self, exporters: Iterable[DatasetExporter] = ()) -> None:
        self._exporters: dict[str, DatasetExporter] = {}
        for exporter in exporters:
            self.register(exporter)

    def register(self, exporter: DatasetExporter) -> None:
        name = exporter.format_name.strip().lower()
        if not name:
            raise ValueError("Exporter format_name must not be empty")
        if name in self._exporters:
            raise ValueError(f"Exporter already registered: {name}")
        self._exporters[name] = exporter

    def get(self, format_name: str) -> DatasetExporter:
        name = format_name.strip().lower()
        try:
            return self._exporters[name]
        except KeyError as error:
            choices = ", ".join(self.names()) or "none"
            raise KeyError(f"Unknown exporter {format_name!r}; registered: {choices}") from error

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._exporters))
