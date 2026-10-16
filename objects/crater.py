"""Crater bowls: a radial terrain patch with a raised rim."""
from __future__ import annotations

import math

import numpy as np

from universe.procedural_generation import crater_profile

from .base import S_CRATER, KindSpec, hsv
from .geometry import MeshData, recompute_normals, wave_noise


def crater_mesh(rings: int = 28, segs: int = 64, outer: float = 1.35, seed: int = 4) -> MeshData:
    rho = np.linspace(0, outer, rings + 1)
    a = np.linspace(0, 2 * math.pi, segs + 1)
    rr, aa = np.meshgrid(rho, a, indexing="ij")
    x, z = rr * np.cos(aa), rr * np.sin(aa)
    y = crater_profile(rr)
    flat = np.stack([x, y, z], -1).reshape(-1, 3)
    y = y + 0.02 * wave_noise(flat * 3.0, seed, 3).reshape(y.shape)
    pos = np.stack([x.reshape(-1), y.reshape(-1), z.reshape(-1)], 1)
    idx = []
    for i in range(rings):
        for j in range(segs):
            p = i * (segs + 1) + j
            q = p + segs + 1
            idx += [p, p + 1, q, p + 1, q + 1, q]
    uv = np.stack([x.reshape(-1), z.reshape(-1)], 1) / (2 * outer) + 0.5
    m = MeshData(pos.astype(np.float32), None, uv.astype(np.float32), np.array(idx, np.uint32))
    return recompute_normals(m)


CRATER = KindSpec(
    "crater", "mesh", [lambda: crater_mesh(28, 64), lambda: crater_mesh(12, 32), lambda: crater_mesh(5, 16)],
    style=S_CRATER, palette=lambda s: hsv(0.07 + 0.05 * s, 0.25, 0.7), pick_scale=1.0,
    description="Impact crater",
)
