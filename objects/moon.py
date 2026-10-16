"""Moons: grey cratered bodies."""
from __future__ import annotations

from .base import S_MOON, KindSpec, hsv
from .geometry import displaced_icosphere


MOON = KindSpec(
    "moon", "mesh",
    [lambda: displaced_icosphere(4, 3, 0.015), lambda: displaced_icosphere(3, 3, 0.015),
     lambda: displaced_icosphere(1, 3, 0.015)],
    style=S_MOON, palette=lambda s: hsv(0.08 + 0.1 * s, 0.12 + 0.1 * s, 0.75 + 0.2 * s),
    description="Moon",
)
