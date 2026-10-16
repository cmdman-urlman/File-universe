"""Planetary systems (a star with orbit rings) and file stars."""
from __future__ import annotations

import numpy as np

from .base import S_STAR, KindSpec, hsv, pick
from .geometry import circle_lines, merge_lines, uv_sphere, MeshData

STAR_COLORS = [(1.0, 0.85, 0.45), (1.0, 0.6, 0.3), (0.75, 0.85, 1.0), (1.0, 0.95, 0.8), (1.0, 0.45, 0.25)]


def system_orbit_lines() -> MeshData:
    rings = []
    for r in (1.9, 2.7, 3.6):
        c = circle_lines(96)
        c.positions = c.positions * r
        rings.append(c)
    return merge_lines(rings)


def _system_scale_down(m: MeshData) -> MeshData:
    m.positions = (m.positions * 0.28).astype(np.float32)
    return m


SYSTEM = KindSpec(
    "system", "mesh",
    [lambda: uv_sphere(24, 48), lambda: uv_sphere(12, 24), lambda: uv_sphere(6, 12)],
    style=S_STAR, emissive=1.0, palette=lambda s: pick(STAR_COLORS, s), glow=3.2,
    lines=system_orbit_lines, line_alpha=0.3, pick_scale=1.0,
    description="Star with planetary system",
)

FILE_STAR = KindSpec(
    "star", "mesh",
    [lambda: uv_sphere(16, 32), lambda: uv_sphere(8, 16), lambda: uv_sphere(4, 8)],
    style=S_STAR, emissive=1.0, palette=lambda s: hsv(0.12, 0.3, 1.0), glow=1.9,
    description="Star (file)",
)
