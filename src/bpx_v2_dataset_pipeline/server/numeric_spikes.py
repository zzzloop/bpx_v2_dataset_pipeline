from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class SpikeRepairResult:
    repaired: np.ndarray
    mask: np.ndarray

    @property
    def count(self) -> int:
        return int(self.mask.sum())


def repair_isolated_spikes(
    values: np.ndarray,
    *,
    jump_thresholds: np.ndarray,
    neighbor_thresholds: np.ndarray,
) -> SpikeRepairResult:
    """Replace only isolated center samples whose two neighbors agree.

    Thresholds are per joint and must be supplied from the finalized robot
    contract; the pipeline deliberately has no guessed hardware defaults.
    """
    source = np.asarray(values)
    if source.ndim != 2 or source.shape[0] < 3:
        raise ValueError("values must have shape (T, D) with T >= 3")
    if not np.issubdtype(source.dtype, np.floating):
        raise ValueError("values must use a floating-point dtype")
    if not np.all(np.isfinite(source)):
        raise ValueError("values contain NaN or infinity")
    dimension = source.shape[1]
    jumps = np.asarray(jump_thresholds, dtype=np.float64)
    neighbors = np.asarray(neighbor_thresholds, dtype=np.float64)
    if jumps.shape != (dimension,) or neighbors.shape != (dimension,):
        raise ValueError("threshold vectors must match the data dimension")
    if np.any(jumps <= 0) or np.any(neighbors < 0):
        raise ValueError("jump thresholds must be positive and neighbor thresholds non-negative")

    previous = source[:-2]
    center = source[1:-1]
    following = source[2:]
    isolated = (
        (np.abs(center - previous) > jumps)
        & (np.abs(center - following) > jumps)
        & (np.abs(previous - following) <= neighbors)
    )
    mask = np.zeros(source.shape, dtype=bool)
    mask[1:-1] = isolated
    repaired = source.copy()
    midpoint = (previous.astype(np.float64) + following.astype(np.float64)) * 0.5
    repaired[1:-1] = np.where(isolated, midpoint, center).astype(source.dtype)
    return SpikeRepairResult(repaired=repaired, mask=mask)
