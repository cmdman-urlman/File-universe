"""Globular star clusters."""
from __future__ import annotations

import numpy as np

from .base import KindSpec, hsv
from .geometry import POINTS, MeshData


def cluster_points(n: int = 1800, seed: int = 5) -> MeshData:
    rng = np.random.default_rng(seed)
    # Plummer-like density profile
    u = rng.random(n)
    r = 0.25 / np.sqrt(np.maximum(u ** (-2.0 / 3.0) - 1.0, 1e-4))
    r = np.clip(r, 0, 1.0)
    d = rng.normal(size=(n, 3))
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    pos = d * r[:, None]
    t = rng.random(n)
    col = np.where(t[:, None] < 0.7, [[1.0, 0.92, 0.75]], [[0.7, 0.82, 1.0]])
    size = 0.05 * (0.5 + rng.random(n)) * (1.4 - r)
    bright = 0.5 + 0.5 * rng.random(n)
    return MeshData(pos.astype(np.float32), mode=POINTS, colors=col.astype(np.float32),
                    sizes=np.stack([size, bright], 1).astype(np.float32))


CLUSTER = KindSpec(
    "cluster", "points", [lambda: cluster_points(2000, 5), lambda: cluster_points(700, 5), lambda: cluster_points(200, 5)],
    palette=lambda s: hsv(0.1 + 0.5 * s, 0.25, 1.0), glow=0.6, pick_scale=0.8,
    description="Globular star cluster",
)
