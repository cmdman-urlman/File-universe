"""Device-shaped universe shells: SSD, HDD, USB stick, optical disc, SD card.

Each builder returns ``(shell, details, edges)``: a translucent glass shell
that contains the universe, opaque hardware details (chips, connectors,
platters...) and glowing outline lines. Dimensions are half-extents.
"""
from __future__ import annotations

import math

import numpy as np

from .base import S_CHIP, S_METAL
from .geometry import (MeshData, box, box_edges, circle_lines, cylinder, extrude_convex, merge,
                       merge_lines, polyline_loop, torus, transform, uv_sphere)

DeviceMeshes = tuple[MeshData, list | MeshData | None, MeshData]


def _ring(r: float, y: float, segs: int = 128) -> MeshData:
    c = circle_lines(segs)
    c.positions = (c.positions * r + [0, y, 0]).astype(np.float32)
    return c


def ssd(hx: float, hy: float, hz: float) -> DeviceMeshes:
    t = hy * 0.5
    shell = box(hx, t, hz)
    chips = []
    # NAND packages + controller on the underside so they never hide the galaxies
    n = 4
    for i in range(n):
        cx = -hx * 0.62 + i * hx * 0.36
        chips.append(transform(box(hx * 0.13, t * 0.05, hz * 0.55), offset=(cx, -t * 1.05, 0)))
    chips.append(transform(box(hx * 0.1, t * 0.06, hz * 0.4), offset=(hx * 0.72, -t * 1.06, 0)))
    contacts = []
    for k in range(10):
        z = -hz * 0.8 + k * hz * 1.6 / 9
        contacts.append(transform(box(hx * 0.035, t * 0.04, hz * 0.05), offset=(hx * 1.035, -t * 0.6, z)))
    edges = box_edges(hx, t, hz)
    return shell, [(merge(chips), S_CHIP), (merge(contacts), S_METAL)], edges


def hdd(hx: float, hy: float, hz: float) -> DeviceMeshes:
    r = hx
    shell = cylinder(r, hy, 96)
    parts = [transform(cylinder(r * 0.06, hy * 1.02, 32), offset=(0, 0, 0))]
    for k, y in enumerate((-0.6, 0.0, 0.6)):
        parts.append(transform(cylinder(r * 0.98, hy * 0.012, 96, inner=r * 0.1), offset=(0, y * hy, 0)))
    # actuator arm reaching from the rim towards the spindle
    arm = box(r * 0.42, hy * 0.05, r * 0.03)
    ang = math.radians(35)
    p = arm.positions.copy()
    c, s = math.cos(ang), math.sin(ang)
    p = p @ np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]]).T
    arm.positions = (p + [r * 0.62, hy * 0.85, r * 0.42]).astype(np.float32)
    parts.append(arm)
    parts.append(transform(cylinder(r * 0.07, hy * 0.9, 24), offset=(r * 0.95, 0, r * 0.67)))
    edges = merge_lines([_ring(r, hy), _ring(r, -hy), _ring(r * 0.98, 0.6 * hy, 96), _ring(r * 0.98, -0.6 * hy, 96)])
    return shell, merge(parts), edges


def usb(hx: float, hy: float, hz: float) -> DeviceMeshes:
    body_len = hx * 0.78
    t = hy * 0.6
    shell = transform(box(body_len, t, hz), offset=(-hx + body_len, 0, 0))
    conn_len = hx - body_len
    cx = hx - conn_len
    parts = [transform(box(conn_len, t * 0.45, hz * 0.62), offset=(cx, 0, 0))]   # metal connector
    parts.append(transform(box(conn_len * 0.25, t * 0.2, hz * 0.12), offset=(cx + conn_len * 0.5, t * 0.3, -hz * 0.25)))
    parts.append(transform(box(conn_len * 0.25, t * 0.2, hz * 0.12), offset=(cx + conn_len * 0.5, t * 0.3, hz * 0.25)))
    parts.append(transform(cylinder(hz * 0.18, t * 1.02, 24), offset=(-hx + hz * 0.45, 0, 0)))  # lanyard hole ring
    parts.append(transform(box(hz * 0.06, t * 0.1, hz * 0.06), offset=(-hx + body_len * 1.6, t * 1.05, 0)))  # LED
    edges = merge_lines([transform_lines(box_edges(body_len, t, hz), (-hx + body_len, 0, 0)),
                         transform_lines(box_edges(conn_len, t * 0.45, hz * 0.62), (cx, 0, 0))])
    return shell, merge(parts), edges


def disc(hx: float, hy: float, hz: float) -> DeviceMeshes:
    r = hx
    hole = r * 0.12
    shell = cylinder(r, hy * 0.25, 128, inner=hole)
    parts = [cylinder(r * 0.3, hy * 0.27, 96, inner=hole * 1.05)]
    edges = merge_lines([_ring(r, hy * 0.25), _ring(r, -hy * 0.25), _ring(hole, hy * 0.25, 48),
                         _ring(r * 0.3, hy * 0.27, 96)])
    return shell, merge(parts), edges


def sd_card(hx: float, hy: float, hz: float) -> DeviceMeshes:
    t = hy * 0.4
    cut = min(hx, hz) * 0.35
    poly = [(-hx, -hz), (hx, -hz), (hx, hz), (-hx + cut, hz), (-hx, hz - cut)]   # CCW from +Y
    poly = [(x, -z) for x, z in poly][::-1]
    shell = extrude_convex(poly, t)
    parts = []
    for k in range(8):
        x = -hx * 0.65 + k * hx * 1.35 / 7
        parts.append(transform(box(hx * 0.06, t * 0.08, hz * 0.12), offset=(x, t * 1.02, -hz * 0.82)))
    parts.append(transform(box(hx * 0.04, t * 0.6, hz * 0.12), offset=(-hx * 1.02, 0, 0.2 * hz)))   # lock switch
    outline = np.array([[x, t, z] for x, z in poly], np.float32)
    outline_b = outline.copy()
    outline_b[:, 1] = -t
    edges = merge_lines([polyline_loop(outline), polyline_loop(outline_b)])
    return shell, merge(parts), edges


def network(hx: float, hy: float, hz: float) -> DeviceMeshes:
    shell = transform(uv_sphere(24, 48), (hx, hy * 0.9, hz))
    parts = [transform(torus(1.0, 0.015, 96, 6), (hx * 1.05, hx * 1.05, hz * 1.05))]
    edges = merge_lines([_ring(hx, 0), _ring(hx * 0.8, hy * 0.5), _ring(hx * 0.8, -hy * 0.5)])
    return shell, merge(parts), edges


def generic(hx: float, hy: float, hz: float) -> DeviceMeshes:
    return box(hx, hy * 0.6, hz), None, box_edges(hx, hy * 0.6, hz)


def transform_lines(m: MeshData, offset) -> MeshData:
    m.positions = (m.positions + np.asarray(offset, np.float32)).astype(np.float32)
    return m


BUILDERS = {"ssd": ssd, "hdd": hdd, "usb": usb, "disc": disc, "sd": sd_card, "network": network,
            "ram": ssd, "unknown": generic}

SHELL_COLORS = {"ssd": (0.35, 0.65, 1.0), "hdd": (0.75, 0.8, 0.9), "usb": (0.3, 1.0, 0.6),
                "disc": (0.95, 0.8, 1.0), "sd": (1.0, 0.75, 0.3), "network": (0.5, 0.9, 1.0),
                "ram": (0.6, 1.0, 0.4), "unknown": (0.8, 0.8, 0.8)}


def build_device(kind: str, half: tuple[float, float, float]) -> DeviceMeshes:
    """Returns (shell, [(details_mesh, style), ...], edges)."""
    shell, details, edges = BUILDERS.get(kind, generic)(*half)
    if details is None:
        details = []
    elif isinstance(details, MeshData):
        details = [(details, S_METAL)]
    return shell, details, edges


DEFAULT_HALF = {
    "ssd": (2.0, 0.6, 1.2), "hdd": (1.8, 0.5, 1.8), "usb": (2.6, 0.5, 0.85),
    "disc": (2.0, 0.4, 2.0), "sd": (1.2, 0.5, 1.5), "network": (1.7, 1.0, 1.7),
    "ram": (2.0, 0.6, 1.2), "unknown": (1.6, 0.8, 1.6),
}


def default_half(kind: str, scale: float = 1.0) -> tuple[float, float, float]:
    return tuple(v * scale for v in DEFAULT_HALF.get(kind, DEFAULT_HALF["unknown"]))
