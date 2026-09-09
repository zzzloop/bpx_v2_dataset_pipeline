from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class PhotometricConfig:
    probability: float = 0.8
    brightness: tuple[float, float] = (0.65, 1.35)
    contrast: tuple[float, float] = (0.85, 1.15)
    gamma: tuple[float, float] = (0.85, 1.15)

    def __post_init__(self) -> None:
        if not 0 <= self.probability <= 1:
            raise ValueError("probability must be in [0, 1]")
        for name in ("brightness", "contrast", "gamma"):
            low, high = getattr(self, name)
            if not 0 < low <= high:
                raise ValueError(f"{name} range must be positive and ordered")


@dataclass(frozen=True, slots=True)
class PhotometricParameters:
    brightness: float
    contrast: float
    gamma: float


def sample_parameters(config: PhotometricConfig, rng: np.random.Generator) -> PhotometricParameters | None:
    if rng.random() >= config.probability:
        return None
    return PhotometricParameters(
        brightness=float(rng.uniform(*config.brightness)),
        contrast=float(rng.uniform(*config.contrast)),
        gamma=float(rng.uniform(*config.gamma)),
    )


def _apply(image: np.ndarray, parameters: PhotometricParameters) -> np.ndarray:
    source = np.asarray(image)
    if source.dtype == np.uint8:
        working = source.astype(np.float32) / 255.0
        output_dtype = np.uint8
    elif np.issubdtype(source.dtype, np.floating):
        working = source.astype(np.float32)
        output_dtype = source.dtype
    else:
        raise ValueError(f"Unsupported image dtype: {source.dtype}")
    if source.ndim < 3 or 3 not in (source.shape[-1], source.shape[-3]):
        raise ValueError(f"Expected RGB image or image sequence, got {source.shape}")
    if working.size and (working.min() < 0 or working.max() > 1):
        raise ValueError("Floating-point images must be in [0, 1]")

    working = np.clip(working * parameters.brightness, 0, 1)
    working = np.clip((working - 0.5) * parameters.contrast + 0.5, 0, 1)
    working = np.clip(working, 0, 1) ** parameters.gamma
    if output_dtype == np.uint8:
        return np.rint(working * 255).astype(np.uint8)
    return working.astype(output_dtype)


def augment_views(
    images: Mapping[str, np.ndarray],
    *,
    config: PhotometricConfig,
    rng: np.random.Generator,
) -> dict[str, np.ndarray]:
    """Apply one shared color-preserving transform to all views/time steps."""
    parameters = sample_parameters(config, rng)
    if parameters is None:
        return {key: np.array(value, copy=True) for key, value in images.items()}
    return {key: _apply(value, parameters) for key, value in images.items()}
