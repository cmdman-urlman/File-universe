"""Spiral galaxies and galaxy regions (nebulae) as particle clouds."""
from __future__ import annotations

import math

import numpy as np

from .base import KindSpec, hsv
from .geometry import POINTS, MeshData


def galaxy_points(n: int = 3500, arms: int = 3, seed: int = 7) -> MeshData:
    rng = np.random.default_rng(seed)
    n_core = n // 5
    n_arm = n - n_core
    # arms: logarithmic spirals with gaussian scatter
    t = rng.random(n_arm) ** 0.7
    arm = rng.integers(0, arms, n_arm)
    theta = arm * (2 * math.pi / arms) + t * 3.4 * math.pi
    r = 0.08 + 0.92 * t
    scatter = 0.07 + 0.08 * t
    x = r * np.cos(theta) + rng.normal(0, scatter, n_arm)
    z = r * np.sin(theta) + rng.normal(0, scatter, n_arm)
    y = rng.normal(0, 0.035 * (1.2 - t), n_arm)
    # bulge
    cr = np.abs(rng.normal(0, 0.12, n_core))
    ca = rng.random(n_core) * 2 * math.pi
    cz = rng.normal(0, 1, n_core)
    cx = cr * np.cos(ca)
    czz = cr * np.sin(ca)
    cy = rng.normal(0, 0.05, n_core) * (1 - np.clip(cr * 4, 0, 1)) + cz * 0.01
    pos = np.concatenate([np.stack([x, y, z], 1), np.stack([cx, cy, czz], 1)])
    tt = np.concatenate([t, np.zeros(n_core)])
    # colours: warm core -> blue arms, with pink HII regions; stored as tint weights
    warm = np.array([1.0, 0.85, 0.6])
    cool = np.array([0.6, 0.75, 1.0])
    col = warm[None] * (1 - tt[:, None]) + cool[None] * tt[:, None]
    hii = rng.random(n) < 0.04
    col[hii] = [1.0, 0.45, 0.7]
    size = np.where(np.arange(n) >= n_arm, 0.10, 0.06) * (0.6 + rng.random(n))
    size[hii] *= 2.2
    bright = 0.35 + 0.65 * rng.random(n)
    bright[n_arm:] = 0.8
    return MeshData(pos.astype(np.float32), mode=POINTS, colors=col.astype(np.float32),
                    sizes=np.stack([size, bright], 1).astype(np.float32))


def nebula_points(n: int = 2600, seed: int = 11) -> MeshData:
    rng = np.random.default_rng(seed)
    blobs = rng.normal(0, 0.45, (9, 3)) * [1, 0.5, 1]
    which = rng.integers(0, len(blobs), n)
    pos = blobs[which] + rng.normal(0, 0.28, (n, 3)) * [1, 0.6, 1]
    d = np.linalg.norm(pos, axis=1)
    pos = pos / np.maximum(d.max(), 1e-6)
    hue_mix = rng.random(n)
    col = np.where(hue_mix[:, None] < 0.6, [[1.0, 0.5, 0.75]], [[0.45, 0.85, 1.0]])
    col = col * (0.7 + 0.3 * rng.random((n, 1)))
    stars = rng.random(n) < 0.12
    col[stars] = [1, 1, 1]
    size = np.where(stars, 0.035, 0.22 * (0.5 + rng.random(n)))
    bright = np.where(stars, 1.0, 0.10 + 0.12 * rng.random(n))
    return MeshData(pos.astype(np.float32), mode=POINTS, colors=col.astype(np.float32),
                    sizes=np.stack([size, bright], 1).astype(np.float32))


GALAXY = KindSpec(
    "galaxy", "points", [lambda: galaxy_points(4200, 3, 7), lambda: galaxy_points(1400, 3, 7), lambda: galaxy_points(350, 3, 7)],
    palette=lambda s: hsv(0.55 + 0.5 * s, 0.35, 1.0), glow=0.55, pick_scale=0.9,
    description="Spiral galaxy",
)

REGION = KindSpec(
    "region", "points", [lambda: nebula_points(2600, 11), lambda: nebula_points(900, 11), lambda: nebula_points(260, 11)],
    palette=lambda s: hsv(0.85 + 0.45 * s, 0.55, 1.0), glow=0.35, pick_scale=0.85,
    description="Emission nebula region",
)
