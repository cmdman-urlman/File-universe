"""Planets (folders) and exoplanets (files)."""
from __future__ import annotations

from .base import S_GAS, S_TERRAIN, KindSpec, hsv
from .geometry import circle_lines, merge_lines, uv_sphere


def _planet_style(seed: float) -> int:
    return S_GAS if seed > 0.62 else S_TERRAIN


def _rings():
    out = []
    for r in (1.55, 1.7, 1.85, 2.0, 2.15):
        c = circle_lines(96)
        c.positions = c.positions * r
        out.append(c)
    return merge_lines(out)


PLANET = KindSpec(
    "planet", "mesh",
    [lambda: uv_sphere(32, 64), lambda: uv_sphere(16, 32), lambda: uv_sphere(8, 16)],
    palette=lambda s: hsv(s * 1.7, 0.45, 0.95), style_for_seed=_planet_style,
    lines=_rings, line_alpha=0.25, description="Planet",
    extra={"ring_threshold": 0.8},   # seeds above this get rings
)

EXOPLANET = KindSpec(
    "exoplanet", "mesh",
    [lambda: uv_sphere(24, 48), lambda: uv_sphere(12, 24), lambda: uv_sphere(6, 12)],
    palette=lambda s: hsv(s, 0.4, 0.9), style_for_seed=_planet_style, description="Exoplanet (file)",
)
