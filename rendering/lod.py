"""Level-of-detail policy based on projected (on-screen) size."""
from __future__ import annotations

import numpy as np

LOD_HIGH_PX = 90.0       # radius in pixels above which the high-detail mesh is used
LOD_MID_PX = 18.0
CULL_PX = 0.35
POINT_CLOUD_MIN_PX = 3.0   # smaller particle clouds are drawn as a single glow sprite           # smaller than this: not drawn at all
SATELLITE_MIN_PX = 26.0  # parent size at which sampled grandchildren appear
SATELLITE_FULL_PX = 70.0
ICON_MIN_PX = 4.0
MAX_ICONS = 180
MAX_LABELS = 70
MAX_BRACKETS = 500


def choose_lod(px: np.ndarray) -> np.ndarray:
    lod = np.full(len(px), 2, np.int32)
    lod[px >= LOD_MID_PX] = 1
    lod[px >= LOD_HIGH_PX] = 0
    return lod


def satellite_alpha(parent_px: np.ndarray) -> np.ndarray:
    return np.clip((parent_px - SATELLITE_MIN_PX) / (SATELLITE_FULL_PX - SATELLITE_MIN_PX), 0.0, 1.0)


def top_k(values: np.ndarray, mask: np.ndarray, k: int) -> np.ndarray:
    """Indices of the k largest values where mask is True (descending)."""
    idx = np.nonzero(mask)[0]
    if len(idx) > k:
        part = np.argpartition(-values[idx], k)[:k]
        idx = idx[part]
    return idx[np.argsort(-values[idx])]
