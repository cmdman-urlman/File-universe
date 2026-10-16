"""Renderable scene: struct-of-arrays description of every visible object.

A scene always shows *one* filesystem location (the "focus"): its own body in
the centre plus its children around it, plus sampled grandchildren as LOD
satellites. Navigating re-roots the scene, so arbitrarily deep hierarchies
never run into floating point precision limits.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .mathutil import rot_y


@dataclass
class SceneItem:
    """Metadata for one pickable object (payload is an FSNode or DeviceInfo)."""
    label: str
    kind: str
    payload: Any = None
    is_dir: bool = False
    is_center: bool = False
    category: str = "other"
    icon_key: str | None = None
    image_texture: str | None = None      # preview key for textured planets
    drawn: bool = True                    # False: logical only (e.g. universe centre)


@dataclass
class Scene:
    title: str = ""
    items: list[SceneItem] = field(default_factory=list)
    base_pos: np.ndarray = field(default_factory=lambda: np.zeros((0, 3), np.float32))
    target_pos: np.ndarray = field(default_factory=lambda: np.zeros((0, 3), np.float32))
    orbit_w: np.ndarray = field(default_factory=lambda: np.zeros(0, np.float32))
    radius: np.ndarray = field(default_factory=lambda: np.zeros(0, np.float32))
    radius_target: np.ndarray = field(default_factory=lambda: np.zeros(0, np.float32))
    color: np.ndarray = field(default_factory=lambda: np.zeros((0, 4), np.float32))
    seed: np.ndarray = field(default_factory=lambda: np.zeros(0, np.float32))
    style: np.ndarray = field(default_factory=lambda: np.zeros(0, np.float32))
    tilt: np.ndarray = field(default_factory=lambda: np.zeros((0, 2), np.float32))
    spin: np.ndarray = field(default_factory=lambda: np.zeros(0, np.float32))
    squash: np.ndarray = field(default_factory=lambda: np.ones(0, np.float32))
    alpha: np.ndarray = field(default_factory=lambda: np.zeros(0, np.float32))
    alpha_target: np.ndarray = field(default_factory=lambda: np.ones(0, np.float32))
    emissive: np.ndarray = field(default_factory=lambda: np.zeros(0, np.float32))
    rings: np.ndarray = field(default_factory=lambda: np.zeros(0, bool))       # draw kind line decoration
    # LOD satellites (sampled grandchildren)
    sat_parent: np.ndarray = field(default_factory=lambda: np.zeros(0, np.int32))
    sat_offset: np.ndarray = field(default_factory=lambda: np.zeros((0, 3), np.float32))
    sat_radius: np.ndarray = field(default_factory=lambda: np.zeros(0, np.float32))   # relative to parent radius
    sat_color: np.ndarray = field(default_factory=lambda: np.zeros((0, 4), np.float32))
    sat_kind: list[str] = field(default_factory=list)
    sat_style: np.ndarray = field(default_factory=lambda: np.zeros(0, np.float32))
    sat_seed: np.ndarray = field(default_factory=lambda: np.zeros(0, np.float32))
    # environment
    shell: tuple | None = None                 # (device_kind, (hx, hy, hz), rgb)
    orbit_rings: list[float] = field(default_factory=list)
    belts: list[tuple[float, float]] = field(default_factory=list)
    star_light: bool = False                   # light from a star at the origin
    nebula_hue: float = 0.6
    view_distance: float = 30.0
    extent: float = 10.0
    hidden_count: int = 0                      # children not rendered (huge folders)
    fade: float = 0.0                          # whole-scene fade-in 0..1
    fade_target: float = 1.0
    dissolving: bool = False
    status_text: str = ""
    payload: Any = None                        # focus FSNode / None for home
    depth: int = 0
    device_kind: str | None = None
    extra: dict = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.items)

    def index_of_payload(self, payload) -> int | None:
        for i, it in enumerate(self.items):
            if it.payload is payload:
                return i
        return None

    def index_of_key(self, key: str) -> int | None:
        for i, it in enumerate(self.items):
            p = it.payload
            if p is not None and getattr(p, "key", None) == key:
                return i
        return None

    # ---- per-frame evaluation -----------------------------------------------
    def animate(self, dt: float) -> None:
        k = 1.0 - np.exp(-dt * 4.0)
        if len(self.radius):
            self.radius += (self.radius_target - self.radius) * k
            self.base_pos += (self.target_pos - self.base_pos) * k
            self.alpha += (self.alpha_target - self.alpha) * min(1.0, dt * 2.5)
        speed = 1.6 if not self.dissolving else 0.9
        self.fade += (self.fade_target - self.fade) * min(1.0, dt * speed * 2.0)

    def world_positions(self, t: float) -> np.ndarray:
        if len(self.base_pos) == 0:
            return self.base_pos
        moving = self.orbit_w != 0
        if not moving.any():
            return self.base_pos
        out = self.base_pos.copy()
        out[moving] = rot_y(self.base_pos[moving], self.orbit_w[moving] * t)
        return out

    def satellite_positions(self, t: float, parent_pos: np.ndarray) -> np.ndarray:
        if len(self.sat_parent) == 0:
            return np.zeros((0, 3), np.float32)
        ang = t * 0.15 + self.sat_seed * 6.283
        off = rot_y(self.sat_offset, ang) * self.radius[self.sat_parent][:, None]
        return parent_pos[self.sat_parent] + off
