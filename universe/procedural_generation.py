"""Deterministic, vectorised layout algorithms for each cosmic level.

All functions take per-object radii (already size-scaled) and per-object seeds
in [0, 1) and return positions in scene units. Placement is area/volume based
so that layouts grow with the number and size of objects and objects rarely
overlap, regardless of how many entries a folder contains.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

GOLDEN_ANGLE = math.pi * (3.0 - math.sqrt(5.0))
PHI_FRAC = (math.sqrt(5.0) - 1.0) / 2.0


@dataclass
class Layout:
    positions: np.ndarray                     # (n, 3)
    orbit_speed: np.ndarray                   # (n,) rad/s about +Y through origin
    normals: np.ndarray | None = None         # (n, 3) surface normals (for orientation)
    extent: float = 0.0                       # radius enclosing the layout
    extra: dict = field(default_factory=dict)


def _empty() -> Layout:
    return Layout(np.zeros((0, 3), np.float32), np.zeros(0, np.float32), None, 0.0)


def _extent(pos: np.ndarray, radii: np.ndarray) -> float:
    if len(pos) == 0:
        return 0.0
    return float(np.max(np.linalg.norm(pos, axis=1) + radii))


def vogel_disk(radii, seeds, inner: float = 0.0, packing: float = 2.6, arms: int = 0,
               twist: float = 0.0, thickness: float = 0.0, jitter: float = 0.0) -> Layout:
    radii = np.asarray(radii, np.float64)
    n = len(radii)
    if n == 0:
        return _empty()
    seeds = np.asarray(seeds, np.float64)
    area = np.cumsum((packing * radii) ** 2)
    R = np.sqrt(inner ** 2 + area)
    k = np.arange(n)
    theta = k * GOLDEN_ANGLE
    if arms > 0:
        arm = k % arms
        base = R.max() if n else 1.0
        theta = arm * (2 * math.pi / arms) + twist * np.log1p(4.0 * R / max(base, 1e-6))
        theta = theta + (seeds - 0.5) * 2.0 * jitter
    elif jitter:
        theta = theta + (seeds - 0.5) * jitter
    s2 = np.modf(seeds * 7.31)[0]
    y = (s2 - 0.5) * thickness * (1.0 - 0.6 * R / max(R.max(), 1e-6))
    pos = np.stack([R * np.cos(theta), y, R * np.sin(theta)], axis=1)
    return Layout(pos.astype(np.float32), np.zeros(n, np.float32), None, _extent(pos, radii))


def fibonacci_directions(n: int) -> np.ndarray:
    if n <= 0:
        return np.zeros((0, 3))
    k = np.arange(n) + 0.5
    z = 1.0 - 2.0 * k / n
    r = np.sqrt(np.clip(1.0 - z * z, 0.0, 1.0))
    phi = k * GOLDEN_ANGLE
    return np.stack([r * np.cos(phi), z, r * np.sin(phi)], axis=1)


def ball(radii, seeds, inner: float = 0.0, packing: float = 2.4, squash: float = 1.0) -> Layout:
    """3-D volume packing (globular clusters, nebulae, microscopic shells)."""
    radii = np.asarray(radii, np.float64)
    n = len(radii)
    if n == 0:
        return _empty()
    seeds = np.asarray(seeds, np.float64)
    vol = np.cumsum((packing * radii) ** 3)
    R = np.cbrt(inner ** 3 + vol)
    # deterministic pseudo-random directions (a golden-ratio sequence would show spirals)
    rng = np.random.default_rng(1234567)
    d = rng.normal(size=(n, 3))
    d /= np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-9)
    d[:, 1] *= squash
    pos = d * R[:, None]
    return Layout(pos.astype(np.float32), np.zeros(n, np.float32), d, _extent(pos, radii))


def orbits(radii, seeds, inner: float, max_rings: int = 18, speed: float = 0.35) -> Layout:
    """Individual orbits for the first objects, an asteroid belt for the rest."""
    radii = np.asarray(radii, np.float64)
    n = len(radii)
    if n == 0:
        return _empty()
    seeds = np.asarray(seeds, np.float64)
    m = min(n, max_rings)
    R = np.zeros(n)
    cur = inner
    for i in range(m):
        gap = 0.5 + 0.6 * radii[i]
        cur += radii[i] + gap
        R[i] = cur
        cur += radii[i]
    theta = seeds * 2 * math.pi
    pos = np.zeros((n, 3))
    pos[:m, 0] = R[:m] * np.cos(theta[:m])
    pos[:m, 2] = R[:m] * np.sin(theta[:m])
    w = np.zeros(n)
    w[:m] = speed / np.sqrt(np.maximum(R[:m], 0.5))
    if n > m:
        belt = vogel_disk(radii[m:], seeds[m:], inner=cur + 1.0, packing=2.4,
                          thickness=1.0 + 0.05 * (n - m) ** 0.5)
        pos[m:] = belt.positions
        Rb = np.linalg.norm(belt.positions[:, [0, 2]], axis=1)
        w[m:] = 0.6 * speed / np.sqrt(np.maximum(Rb, 0.5))
    rings = R[:m].astype(np.float32)
    lay = Layout(pos.astype(np.float32), w.astype(np.float32), None, _extent(pos, radii))
    lay.extra["rings"] = rings
    if n > m:
        lay.extra["belt"] = (float(cur + 1.0), float(lay.extent))
    return lay


def surface_radius_needed(radii, base: float, packing: float = 2.3) -> float:
    radii = np.asarray(radii, np.float64)
    if len(radii) == 0:
        return base
    needed = math.sqrt(float(np.sum((packing * radii) ** 2)) / (4 * math.pi))
    return max(base, needed)


def surface(radii, seeds, center_radius: float, embed: float = 0.35) -> Layout:
    """Objects standing on the surface of a sphere of *center_radius*."""
    radii = np.asarray(radii, np.float64)
    n = len(radii)
    if n == 0:
        return _empty()
    d = fibonacci_directions(n)
    # rotate the spiral per container so different planets do not look identical
    pos = d * (center_radius + radii * (1.0 - embed))[:, None]
    return Layout(pos.astype(np.float32), np.zeros(n, np.float32), d.astype(np.float32), _extent(pos, radii))


def crater_profile(rho):
    """Height of a crater bowl (unit radius) at normalised distance rho."""
    rho = np.asarray(rho, np.float64)
    inside = -0.22 + 0.30 * np.clip((rho - 0.3) / 0.7, 0.0, 1.0) ** 2
    outside = 0.08 * np.exp(-((rho - 1.0) / 0.25) ** 2)
    return np.where(rho <= 1.0, inside, outside)


def bowl(radii, seeds, min_radius: float) -> tuple[Layout, float]:
    """Objects lying on the floor of a crater; returns (layout, crater radius)."""
    radii = np.asarray(radii, np.float64)
    disk = vogel_disk(radii, seeds, inner=0.0, packing=2.3)
    if len(radii) == 0:
        return disk, min_radius
    planar = np.linalg.norm(disk.positions[:, [0, 2]], axis=1) + radii
    crater_r = max(min_radius, float(planar.max()) / 0.85)
    rho = np.linalg.norm(disk.positions[:, [0, 2]], axis=1) / crater_r
    pos = disk.positions.astype(np.float64)
    pos[:, 1] = crater_profile(rho) * crater_r + radii * 0.75
    lay = Layout(pos.astype(np.float32), np.zeros(len(radii), np.float32), None, _extent(pos, radii))
    return lay, crater_r


DEVICE_ASPECT = {"ssd": 1.7, "usb": 3.0, "sd": 0.8, "hdd": 1.0, "disc": 1.0,
                 "network": 1.0, "ram": 1.4, "unknown": 1.0}


def device_layout(radii, seeds, device_kind: str) -> tuple[Layout, tuple[float, float, float]]:
    """Place galaxies inside a device-shaped universe; returns (layout, shell half-size xyz)."""
    radii = np.asarray(radii, np.float64)
    inner = 0.0
    if device_kind == "disc":
        inner = 2.0 + 1.5 * math.sqrt(max(len(radii), 1)) * 0.5
    disk = vogel_disk(radii, seeds, inner=inner, packing=2.5, thickness=0.6)
    a = DEVICE_ASPECT.get(device_kind, 1.0)
    pos = disk.positions.astype(np.float64)
    if a != 1.0 and len(pos):
        # area-preserving square-ish stretch of the disk into the footprint
        pos[:, 0] *= math.sqrt(a)
        pos[:, 2] /= math.sqrt(a)
    ext_x = float(np.max(np.abs(pos[:, 0]) + radii)) if len(pos) else 3.0
    ext_z = float(np.max(np.abs(pos[:, 2]) + radii)) if len(pos) else 3.0
    max_r = float(radii.max()) if len(radii) else 1.0
    if device_kind in ("hdd", "disc", "network", "unknown"):
        e = max(ext_x, ext_z, 3.0) * 1.12
        half = (e, max(0.8, max_r * 1.5), e)
    else:
        hx = max(ext_x * 1.12, 3.0 * math.sqrt(a))
        hz = max(ext_z * 1.12, 3.0 / math.sqrt(a))
        # enforce the device's proportions
        if hx / hz < a:
            hx = hz * a
        else:
            hz = hx / a
        half = (hx, max(0.8, max_r * 1.5), hz)
    lay = Layout(pos.astype(np.float32), np.zeros(len(radii), np.float32), None, _extent(pos, radii))
    return lay, half


def satellite_offsets(n: int, parent_radius: float, seed: float) -> np.ndarray:
    """Relative positions for LOD preview satellites around a parent object."""
    if n <= 0:
        return np.zeros((0, 3), np.float32)
    d = fibonacci_directions(n)
    k = np.arange(n)
    shell = parent_radius * (1.45 + 0.55 * np.modf(k * PHI_FRAC + seed)[0])
    ang = seed * 2 * math.pi
    c, s = math.cos(ang), math.sin(ang)
    rot = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    return ((d @ rot.T) * shell[:, None]).astype(np.float32)


def orientation_from_normals(normals: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Tilt angles (about X then Z) that rotate +Y onto each normal."""
    n = np.asarray(normals, np.float64)
    a = np.arcsin(np.clip(n[:, 2], -1, 1))
    b = np.arctan2(-n[:, 0], n[:, 1])
    return a.astype(np.float32), b.astype(np.float32)
