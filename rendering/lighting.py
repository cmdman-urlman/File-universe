"""Scene lighting setup.

Planetary systems are lit by their central star (a point light at the origin,
giving day/night terminators on orbiting planets). Other levels use a fixed
key light plus ambient. Shadow mapping is intentionally not used: at these
scales terminator shading reads better and keeps the frame rate high.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Lighting:
    star_light: bool
    light_pos: tuple[float, float, float] = (0.0, 0.0, 0.0)


def lighting_for(scene) -> Lighting:
    if scene is not None and scene.star_light:
        return Lighting(True, (0.0, 0.0, 0.0))
    return Lighting(False, (0.0, 0.0, 0.0))
