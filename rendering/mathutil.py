"""Small numpy matrix helpers (column-vector convention, matrices row-major in numpy)."""
from __future__ import annotations

import math

import numpy as np


def perspective(fov_y_deg: float, aspect: float, near: float, far: float) -> np.ndarray:
    f = 1.0 / math.tan(math.radians(fov_y_deg) / 2.0)
    m = np.zeros((4, 4), np.float32)
    m[0, 0] = f / max(aspect, 1e-6)
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = 2 * far * near / (near - far)
    m[3, 2] = -1.0
    return m


def look_at(eye, target, up=(0.0, 1.0, 0.0)) -> np.ndarray:
    eye = np.asarray(eye, np.float64)
    target = np.asarray(target, np.float64)
    f = target - eye
    f /= max(np.linalg.norm(f), 1e-12)
    s = np.cross(f, up)
    if np.linalg.norm(s) < 1e-9:
        s = np.cross(f, (0.0, 0.0, 1.0))
    s /= np.linalg.norm(s)
    u = np.cross(s, f)
    m = np.eye(4, dtype=np.float32)
    m[0, :3], m[1, :3], m[2, :3] = s, u, -f
    m[0, 3], m[1, 3], m[2, 3] = -np.dot(s, eye), -np.dot(u, eye), np.dot(f, eye)
    return m


def frustum_planes(view_proj: np.ndarray) -> np.ndarray:
    """Six normalised planes (a, b, c, d); inside when a*x+b*y+c*z+d >= 0."""
    m = view_proj
    planes = np.array([m[3] + m[0], m[3] - m[0], m[3] + m[1], m[3] - m[1], m[3] + m[2], m[3] - m[2]], np.float64)
    planes /= np.linalg.norm(planes[:, :3], axis=1, keepdims=True)
    return planes


def spheres_in_frustum(planes: np.ndarray, centers: np.ndarray, radii: np.ndarray) -> np.ndarray:
    if len(centers) == 0:
        return np.zeros(0, bool)
    d = centers @ planes[:, :3].T + planes[:, 3]
    return np.all(d >= -radii[:, None], axis=1)


def project(view_proj: np.ndarray, points: np.ndarray, width: int, height: int):
    """World points -> (screen xy pixels, clip w)."""
    n = len(points)
    hom = np.concatenate([points, np.ones((n, 1))], axis=1) @ view_proj.T
    w = hom[:, 3]
    safe = np.where(np.abs(w) < 1e-9, 1e-9, w)
    ndc = hom[:, :2] / safe[:, None]
    sx = (ndc[:, 0] * 0.5 + 0.5) * width
    sy = (1.0 - (ndc[:, 1] * 0.5 + 0.5)) * height
    return np.stack([sx, sy], axis=1), w


def ray_sphere(origin, direction, centers, radii):
    """Distance along the ray to each sphere (inf where missed)."""
    oc = centers - origin
    b = oc @ direction
    c = np.einsum("ij,ij->i", oc, oc) - radii ** 2
    disc = b * b - c
    hit = disc >= 0
    t = np.full(len(centers), np.inf)
    sq = np.sqrt(np.where(hit, disc, 0))
    t0 = b - sq
    t1 = b + sq
    tt = np.where(t0 > 0, t0, t1)
    ok = hit & (tt > 0)
    t[ok] = tt[ok]
    return t


def rot_y(points: np.ndarray, angles: np.ndarray) -> np.ndarray:
    c, s = np.cos(angles), np.sin(angles)
    out = points.copy()
    out[:, 0] = points[:, 0] * c - points[:, 2] * s
    out[:, 2] = points[:, 0] * s + points[:, 2] * c
    return out
