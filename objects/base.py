"""Common description of a renderable object kind."""
from __future__ import annotations

import colorsys
from dataclasses import dataclass, field
from typing import Callable

from .geometry import MeshData

# Shader material styles (must match rendering/shaders.py)
S_TERRAIN, S_GAS, S_MOON, S_ROCK, S_SAND, S_STAR, S_CRYSTAL, S_CELL, S_PLAIN, S_GLASS, \
    S_CRATER, S_METAL, S_TEXTURED, S_ENERGY, S_CHIP = range(15)


@dataclass
class KindSpec:
    kind: str
    draw: str                                         # "mesh" or "points"
    lods: list[Callable[[], MeshData]]                # high -> low detail builders
    style: int = S_PLAIN
    emissive: float = 0.0
    palette: Callable[[float], tuple[float, float, float]] = lambda s: (0.8, 0.8, 0.8)
    style_for_seed: Callable[[float], int] | None = None
    glow: float = 0.0                                 # corona billboard size (x radius), 0 = none
    lines: Callable[[], MeshData] | None = None       # decorative line mesh (rings, orbits)
    line_alpha: float = 0.35
    pick_scale: float = 1.0
    description: str = ""
    extra: dict = field(default_factory=dict)

    def style_of(self, seed: float) -> int:
        return self.style_for_seed(seed) if self.style_for_seed else self.style


def hsv(h: float, s: float, v: float) -> tuple[float, float, float]:
    return colorsys.hsv_to_rgb(h % 1.0, max(0.0, min(1.0, s)), max(0.0, min(1.0, v)))


def pick(palette: list[tuple[float, float, float]], seed: float) -> tuple[float, float, float]:
    return palette[int(seed * len(palette)) % len(palette)]
