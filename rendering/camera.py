"""Smoothed orbit camera with scripted fly-to animations."""
from __future__ import annotations

import math

import numpy as np

from .mathutil import look_at, perspective


def _smooth(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


class OrbitCamera:
    FOV = 50.0

    def __init__(self):
        self.target = np.zeros(3)
        self.distance = 30.0
        self.yaw = math.radians(35)
        self.pitch = math.radians(28)
        # goals the smoothed values chase
        self.g_target = self.target.copy()
        self.g_distance = self.distance
        self.g_yaw = self.yaw
        self.g_pitch = self.pitch
        self.min_distance = 0.05
        self.max_distance = 5000.0
        self._anim = None    # (t0, duration, from(tuple), to(tuple))
        self.time = 0.0
        self.auto_rotate = 0.0

    # ---- user input -------------------------------------------------------
    def rotate(self, dyaw: float, dpitch: float) -> None:
        self._anim = None
        self.g_yaw += dyaw
        self.g_pitch = max(math.radians(-88), min(math.radians(88), self.g_pitch + dpitch))

    def zoom(self, factor: float) -> None:
        self._anim = None
        self.g_distance = max(self.min_distance, min(self.max_distance, self.g_distance * factor))

    def pan(self, dx: float, dy: float) -> None:
        """Pan in screen space; dx, dy in fractions of the view height."""
        self._anim = None
        right, up, _ = self.basis()
        scale = self.g_distance * math.tan(math.radians(self.FOV) / 2) * 2
        self.g_target = self.g_target + (-right * dx + up * dy) * scale

    def set_view(self, target, distance, yaw=None, pitch=None, immediate=False) -> None:
        self._anim = None
        self.g_target = np.asarray(target, float).copy()
        self.g_distance = float(distance)
        if yaw is not None:
            self.g_yaw = yaw
        if pitch is not None:
            self.g_pitch = pitch
        if immediate:
            self.target = self.g_target.copy()
            self.distance = self.g_distance
            self.yaw, self.pitch = self.g_yaw, self.g_pitch

    def fly_to(self, target, distance, duration: float = 0.9, yaw=None, pitch=None) -> None:
        start = (self.target.copy(), self.distance, self.yaw, self.pitch)
        end = (np.asarray(target, float).copy(), float(distance),
               self.yaw if yaw is None else yaw, self.pitch if pitch is None else pitch)
        self._anim = (self.time, max(duration, 1e-3), start, end)

    @property
    def animating(self) -> bool:
        return self._anim is not None

    def animation_progress(self) -> float:
        if self._anim is None:
            return 1.0
        t0, dur, _, _ = self._anim
        return max(0.0, min(1.0, (self.time - t0) / dur))

    # ---- per frame ----------------------------------------------------------
    def update(self, dt: float) -> None:
        self.time += dt
        if self._anim is not None:
            t0, dur, (pa, da, ya, pia), (pb, db, yb, pib) = self._anim
            u = _smooth((self.time - t0) / dur)
            # interpolate distance logarithmically for a natural zoom feel
            self.distance = math.exp(math.log(max(da, 1e-6)) * (1 - u) + math.log(max(db, 1e-6)) * u)
            self.target = pa * (1 - u) + pb * u
            self.yaw = ya + (yb - ya) * u
            self.pitch = pia + (pib - pia) * u
            self.g_target, self.g_distance, self.g_yaw, self.g_pitch = self.target.copy(), self.distance, self.yaw, self.pitch
            if (self.time - t0) >= dur:
                self._anim = None
            return
        self.g_yaw += self.auto_rotate * dt
        k = 1.0 - math.exp(-dt * 10.0)
        self.target = self.target + (self.g_target - self.target) * k
        self.distance = math.exp(math.log(self.distance) + (math.log(self.g_distance) - math.log(self.distance)) * k)
        self.yaw += (self.g_yaw - self.yaw) * k
        self.pitch += (self.g_pitch - self.pitch) * k

    # ---- matrices -----------------------------------------------------------
    def eye(self) -> np.ndarray:
        cp = math.cos(self.pitch)
        offset = np.array([cp * math.cos(self.yaw), math.sin(self.pitch), cp * math.sin(self.yaw)])
        return self.target + offset * self.distance

    def basis(self):
        eye = self.eye()
        f = self.target - eye
        f /= max(np.linalg.norm(f), 1e-12)
        r = np.cross(f, (0, 1, 0))
        r /= max(np.linalg.norm(r), 1e-12)
        u = np.cross(r, f)
        return r, u, f

    def view(self) -> np.ndarray:
        return look_at(self.eye(), self.target)

    def near_far(self) -> tuple[float, float]:
        return max(self.distance * 0.01, 1e-4), max(self.distance * 400.0, 50.0)

    def projection(self, aspect: float) -> np.ndarray:
        n, f = self.near_far()
        return perspective(self.FOV, aspect, n, f)

    def pixels_per_unit(self, depth: np.ndarray, viewport_h: int) -> np.ndarray:
        return (viewport_h * 0.5) / (np.maximum(depth, 1e-6) * math.tan(math.radians(self.FOV) / 2))

    def ray(self, sx: float, sy: float, width: int, height: int):
        """World-space ray (origin, dir) through a screen pixel."""
        r, u, f = self.basis()
        th = math.tan(math.radians(self.FOV) / 2)
        aspect = width / max(height, 1)
        nx = (2 * sx / max(width, 1) - 1) * th * aspect
        ny = (1 - 2 * sy / max(height, 1)) * th
        d = f + r * nx + u * ny
        return self.eye(), d / np.linalg.norm(d)
