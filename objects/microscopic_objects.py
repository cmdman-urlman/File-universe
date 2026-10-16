"""Rocks, sand grains and the microscopic world (plus small file objects)."""
from __future__ import annotations

import math

import numpy as np

from .base import S_CELL, S_CRYSTAL, S_ENERGY, S_PLAIN, S_ROCK, S_SAND, KindSpec, hsv
from .geometry import (MeshData, circle_lines, crystal, displaced_icosphere, flat_shaded, icosphere,
                       merge, merge_lines, torus, transform, uv_sphere)


def molecule_mesh(subdiv: int = 2) -> MeshData:
    rng = np.random.default_rng(21)
    parts = [transform(icosphere(subdiv), (0.42,) * 3)]
    for i in range(6):
        d = rng.normal(size=3)
        d /= np.linalg.norm(d)
        parts.append(transform(icosphere(subdiv), (0.26,) * 3, d * 0.62))
        # bond: thin elongated sphere between the atoms
        mid = d * 0.31
        bond = icosphere(1)
        bond.positions = bond.positions * 0.07
        bond.positions = bond.positions + (bond.positions @ np.outer(d, d)) * 4.0 + mid
        parts.append(bond)
    return merge(parts)


def atom_mesh(subdiv: int = 2) -> MeshData:
    parts = []
    rng = np.random.default_rng(3)
    for i in range(7):
        d = rng.normal(size=3) * 0.18
        parts.append(transform(icosphere(subdiv), (0.2,) * 3, d))
    return merge(parts)


def atom_orbits() -> MeshData:
    out = []
    for k, (rx, rz) in enumerate(((0, 0), (math.pi / 3, 0.3), (-math.pi / 3, -0.3))):
        c = circle_lines(96)
        p = c.positions * 1.0
        cx, sx = math.cos(rx), math.sin(rx)
        p = p @ np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]]).T
        cz, sz = math.cos(rz), math.sin(rz)
        p = p @ np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]).T
        c.positions = p.astype(np.float32)
        out.append(c)
    return merge_lines(out)


def microbe_mesh(lat=20, lon=40) -> MeshData:
    m = uv_sphere(lat, lon)
    p = m.positions.astype(np.float64)
    # capsule-like bacterium with wobbly membrane
    p[:, 0] *= 1.0 + 0.6 * np.abs(p[:, 0])
    p *= 1.0 + 0.04 * np.sin(p[:, 1:2] * 9.0) * np.cos(p[:, 0:1] * 7.0)
    m.positions = (p / np.abs(p).max()).astype(np.float32)
    from .geometry import recompute_normals
    return recompute_normals(m)


def octahedron() -> MeshData:
    return flat_shaded(icosphere(0))


ROCK = KindSpec(
    "rock", "mesh",
    [lambda: displaced_icosphere(3, 9, 0.28, (1, 0.75, 1), flat=False), lambda: displaced_icosphere(2, 9, 0.28, (1, 0.75, 1)),
     lambda: displaced_icosphere(1, 9, 0.28, (1, 0.75, 1), flat=True)],
    style=S_ROCK, palette=lambda s: hsv(0.06 + 0.06 * s, 0.25 + 0.15 * s, 0.55 + 0.25 * s), description="Rock",
)

GRAIN = KindSpec(
    "grain", "mesh",
    [lambda: displaced_icosphere(2, 17, 0.18, flat=True), lambda: displaced_icosphere(1, 17, 0.18, flat=True),
     lambda: displaced_icosphere(0, 17, 0.18, flat=True)],
    style=S_SAND, palette=lambda s: hsv(0.10 + 0.04 * s, 0.35, 0.85 + 0.1 * s), description="Sand grain (quartz)",
)

MICROBE = KindSpec(
    "microbe", "mesh", [lambda: microbe_mesh(20, 40), lambda: microbe_mesh(10, 20), lambda: microbe_mesh(6, 10)],
    style=S_CELL, palette=lambda s: hsv(0.25 + 0.3 * s, 0.6, 0.85), description="Microbe",
)

MOLECULE = KindSpec(
    "molecule", "mesh", [lambda: molecule_mesh(2), lambda: molecule_mesh(1), lambda: molecule_mesh(0)],
    style=S_PLAIN, palette=lambda s: hsv(0.55 + 0.4 * s, 0.5, 0.95), description="Molecule",
)

ATOM = KindSpec(
    "atom", "mesh", [lambda: atom_mesh(2), lambda: atom_mesh(1), lambda: atom_mesh(0)],
    style=S_PLAIN, emissive=0.35, palette=lambda s: hsv(0.6 + 0.2 * s, 0.55, 1.0), glow=1.6,
    lines=atom_orbits, line_alpha=0.6, description="Atom",
)

QUANTUM = KindSpec(
    "quantum", "mesh", [lambda: torus(0.75, 0.25, 48, 16), lambda: torus(0.75, 0.25, 24, 8), lambda: torus(0.75, 0.25, 12, 6)],
    style=S_ENERGY, emissive=0.8, palette=lambda s: hsv(0.75 + 0.3 * s, 0.7, 1.0), glow=2.0,
    description="Quantum particle",
)

# ---- file objects --------------------------------------------------------
CRYSTAL = KindSpec(
    "crystal", "mesh", [lambda: crystal(6, 1.0), lambda: crystal(6, 1.0), lambda: crystal(4, 1.0)],
    style=S_CRYSTAL, emissive=0.25, palette=lambda s: (0.8, 0.9, 1.0), description="Surface crystal (file)",
)

PEBBLE = KindSpec(
    "pebble", "mesh",
    [lambda: displaced_icosphere(2, 31, 0.2, (1, 0.6, 1)), lambda: displaced_icosphere(1, 31, 0.2, (1, 0.6, 1), flat=True),
     lambda: displaced_icosphere(0, 31, 0.2, (1, 0.6, 1), flat=True)],
    style=S_ROCK, palette=lambda s: (0.7, 0.7, 0.7), description="Pebble (file)",
)

PARTICLE = KindSpec(
    "particle", "mesh", [octahedron, octahedron, octahedron],
    style=S_CRYSTAL, emissive=0.45, palette=lambda s: (0.9, 0.9, 1.0), glow=1.4, description="Particle (file)",
)
