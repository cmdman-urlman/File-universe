"""Procedural mesh primitives (pure numpy; no OpenGL here).

Triangle meshes carry positions, normals, uvs and indices. Point clouds use
``colors`` (rgb) and ``sizes`` (size, brightness). Line meshes use positions
and indices pairs.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

TRIANGLES, POINTS, LINES = "triangles", "points", "lines"


@dataclass
class MeshData:
    positions: np.ndarray
    normals: np.ndarray | None = None
    uvs: np.ndarray | None = None
    indices: np.ndarray | None = None
    mode: str = TRIANGLES
    colors: np.ndarray | None = None      # points
    sizes: np.ndarray | None = None       # points: (size, brightness)

    def vertex_array(self) -> np.ndarray:
        """Interleaved float32 array with 8 floats per vertex."""
        n = len(self.positions)
        out = np.zeros((n, 8), np.float32)
        out[:, 0:3] = self.positions
        if self.mode == POINTS:
            if self.colors is not None:
                out[:, 3:6] = self.colors
            if self.sizes is not None:
                out[:, 6:8] = self.sizes
        else:
            if self.normals is not None:
                out[:, 3:6] = self.normals
            if self.uvs is not None:
                out[:, 6:8] = self.uvs
        return out


def merge(meshes: list[MeshData]) -> MeshData:
    pos, nrm, uv, idx = [], [], [], []
    base = 0
    for m in meshes:
        pos.append(m.positions)
        nrm.append(m.normals if m.normals is not None else np.zeros_like(m.positions))
        uv.append(m.uvs if m.uvs is not None else np.zeros((len(m.positions), 2)))
        idx.append(m.indices + base)
        base += len(m.positions)
    return MeshData(np.concatenate(pos).astype(np.float32), np.concatenate(nrm).astype(np.float32),
                    np.concatenate(uv).astype(np.float32), np.concatenate(idx).astype(np.uint32),
                    meshes[0].mode)


def transform(m: MeshData, scale=(1, 1, 1), offset=(0, 0, 0)) -> MeshData:
    s = np.asarray(scale, np.float32)
    p = m.positions * s + np.asarray(offset, np.float32)
    n = None
    if m.normals is not None:
        n = m.normals / np.where(s == 0, 1, s)
        n = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
    return MeshData(p.astype(np.float32), None if n is None else n.astype(np.float32), m.uvs, m.indices, m.mode)


def uv_sphere(lat: int = 24, lon: int = 48) -> MeshData:
    v = np.linspace(0, 1, lat + 1)
    u = np.linspace(0, 1, lon + 1)
    uu, vv = np.meshgrid(u, v)
    theta = vv * math.pi
    phi = uu * 2 * math.pi
    x = np.sin(theta) * np.cos(phi)
    y = np.cos(theta)
    z = np.sin(theta) * np.sin(phi)
    pos = np.stack([x, y, z], axis=-1).reshape(-1, 3)
    uvs = np.stack([uu, vv], axis=-1).reshape(-1, 2)
    idx = []
    for i in range(lat):
        for j in range(lon):
            a = i * (lon + 1) + j
            b = a + lon + 1
            idx += [a, b, a + 1, a + 1, b, b + 1]
    return MeshData(pos.astype(np.float32), pos.astype(np.float32), uvs.astype(np.float32),
                    np.asarray(idx, np.uint32))


def icosphere(subdiv: int = 2) -> MeshData:
    t = (1.0 + math.sqrt(5.0)) / 2.0
    verts = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t),
             (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
    faces = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4), (11, 10, 2),
             (10, 7, 6), (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5),
             (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)]
    verts = [np.array(v, float) / np.linalg.norm(v) for v in verts]
    for _ in range(subdiv):
        cache: dict[tuple[int, int], int] = {}
        new_faces = []

        def mid(a, b):
            key = (min(a, b), max(a, b))
            if key not in cache:
                m = verts[a] + verts[b]
                verts.append(m / np.linalg.norm(m))
                cache[key] = len(verts) - 1
            return cache[key]
        for a, b, c in faces:
            ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
            new_faces += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
        faces = new_faces
    pos = np.array(verts, np.float32)
    uvs = np.stack([0.5 + np.arctan2(pos[:, 2], pos[:, 0]) / (2 * math.pi), np.arccos(np.clip(pos[:, 1], -1, 1)) / math.pi], 1)
    return MeshData(pos, pos.copy(), uvs.astype(np.float32), np.asarray(faces, np.uint32).reshape(-1))


def flat_shaded(m: MeshData) -> MeshData:
    """Unshare vertices so each triangle gets its own facet normal."""
    tri = m.positions[m.indices.reshape(-1, 3)]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
    pos = tri.reshape(-1, 3)
    nrm = np.repeat(n, 3, axis=0)
    uv = m.uvs[m.indices] if m.uvs is not None else None
    return MeshData(pos.astype(np.float32), nrm.astype(np.float32), uv, np.arange(len(pos), dtype=np.uint32))


def recompute_normals(m: MeshData) -> MeshData:
    tri = m.indices.reshape(-1, 3)
    p = m.positions.astype(np.float64)
    fn = np.cross(p[tri[:, 1]] - p[tri[:, 0]], p[tri[:, 2]] - p[tri[:, 0]])
    n = np.zeros_like(p)
    for k in range(3):
        np.add.at(n, tri[:, k], fn)
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
    m.normals = n.astype(np.float32)
    return m


def wave_noise(p: np.ndarray, seed: int, octaves: int = 4, freq: float = 1.5) -> np.ndarray:
    """Cheap deterministic smooth noise from summed random-direction sine waves."""
    rng = np.random.default_rng(seed)
    out = np.zeros(len(p))
    amp = 1.0
    for _ in range(octaves):
        for _ in range(4):
            d = rng.normal(size=3)
            d /= np.linalg.norm(d)
            out += amp * np.sin(p @ d * freq + rng.uniform(0, 6.28))
        amp *= 0.5
        freq *= 2.1
    return out / 4.0


def displaced_icosphere(subdiv: int, seed: int, amount: float, squash=(1, 1, 1), flat=False) -> MeshData:
    m = icosphere(subdiv)
    d = wave_noise(m.positions.astype(np.float64), seed)
    m.positions = (m.positions * (1.0 + amount * d)[:, None] * np.asarray(squash)).astype(np.float32)
    m = recompute_normals(m)
    return flat_shaded(m) if flat else m


def box(hx=1.0, hy=1.0, hz=1.0) -> MeshData:
    faces = [((1, 0, 0), (0, 1, 0)), ((-1, 0, 0), (0, 1, 0)), ((0, 1, 0), (0, 0, 1)),
             ((0, -1, 0), (0, 0, 1)), ((0, 0, 1), (0, 1, 0)), ((0, 0, -1), (0, 1, 0))]
    pos, nrm, uv, idx = [], [], [], []
    h = np.array([hx, hy, hz])
    for n, up in faces:
        n, up = np.array(n, float), np.array(up, float)
        right = np.cross(up, n)
        base = len(pos)
        for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            pos.append((n + right * su + up * sv) * h)
            nrm.append(n)
            uv.append(((su + 1) / 2, (sv + 1) / 2))
        idx += [base, base + 1, base + 2, base, base + 2, base + 3]
    return MeshData(np.array(pos, np.float32), np.array(nrm, np.float32), np.array(uv, np.float32),
                    np.array(idx, np.uint32))


def cylinder(radius=1.0, half_h=1.0, segs=48, inner=0.0) -> MeshData:
    """Closed cylinder, or a tube/annulus when *inner* > 0."""
    a = np.linspace(0, 2 * math.pi, segs + 1)
    c, s = np.cos(a), np.sin(a)
    parts = []

    def side(r, outward):
        pos, nrm, idx = [], [], []
        for i in range(segs + 1):
            for y in (-half_h, half_h):
                pos.append((r * c[i], y, r * s[i]))
                nrm.append((c[i] * outward, 0, s[i] * outward))
        for i in range(segs):
            a0 = 2 * i
            tri = [a0, a0 + 1, a0 + 2, a0 + 1, a0 + 3, a0 + 2]
            if outward < 0:
                tri = [tri[0], tri[2], tri[1], tri[3], tri[5], tri[4]]
            idx += tri
        return MeshData(np.array(pos, np.float32), np.array(nrm, np.float32),
                        np.zeros((len(pos), 2), np.float32), np.array(idx, np.uint32))

    def cap(y, up):
        pos, nrm, idx = [], [], []
        for i in range(segs + 1):
            pos.append((radius * c[i], y, radius * s[i]))
            pos.append((inner * c[i], y, inner * s[i]))
            nrm += [(0, up, 0)] * 2
        for i in range(segs):
            a0 = 2 * i
            tri = [a0, a0 + 2, a0 + 1, a0 + 1, a0 + 2, a0 + 3]
            if up < 0:
                tri = [tri[0], tri[2], tri[1], tri[3], tri[5], tri[4]]
            idx += tri
        uv = np.array(pos, np.float32)[:, [0, 2]] / (2 * radius) + 0.5
        return MeshData(np.array(pos, np.float32), np.array(nrm, np.float32), uv.astype(np.float32),
                        np.array(idx, np.uint32))

    parts.append(side(radius, 1))
    if inner > 0:
        parts.append(side(inner, -1))
    parts += [cap(half_h, 1), cap(-half_h, -1)]
    return merge(parts)


def torus(R=1.0, r=0.25, segs=48, rings=16) -> MeshData:
    u = np.linspace(0, 2 * math.pi, segs + 1)
    v = np.linspace(0, 2 * math.pi, rings + 1)
    uu, vv = np.meshgrid(u, v)
    x = (R + r * np.cos(vv)) * np.cos(uu)
    z = (R + r * np.cos(vv)) * np.sin(uu)
    y = r * np.sin(vv)
    pos = np.stack([x, y, z], -1).reshape(-1, 3)
    cen = np.stack([R * np.cos(uu), np.zeros_like(uu), R * np.sin(uu)], -1).reshape(-1, 3)
    nrm = pos - cen
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True)
    idx = []
    for i in range(rings):
        for j in range(segs):
            a = i * (segs + 1) + j
            b = a + segs + 1
            idx += [a, a + 1, b, a + 1, b + 1, b]
    uv = np.stack([uu / (2 * math.pi), vv / (2 * math.pi)], -1).reshape(-1, 2)
    return MeshData(pos.astype(np.float32), nrm.astype(np.float32), uv.astype(np.float32), np.array(idx, np.uint32))


def extrude_convex(poly: list[tuple[float, float]], half_h: float) -> MeshData:
    """Extrude a convex polygon (x, z points, counter-clockwise seen from +Y)."""
    pts = np.array(poly, float)
    n = len(pts)
    parts = []
    for y, up in ((half_h, 1), (-half_h, -1)):
        pos = np.column_stack([pts[:, 0], np.full(n, y), pts[:, 1]])
        idx = []
        for i in range(1, n - 1):
            idx += [0, i + 1, i] if up > 0 else [0, i, i + 1]
        lo, hi = pts.min(0), pts.max(0)
        uv = (pts - lo) / np.maximum(hi - lo, 1e-6)
        parts.append(MeshData(pos.astype(np.float32), np.tile([0, up, 0], (n, 1)).astype(np.float32),
                              uv.astype(np.float32), np.array(idx, np.uint32)))
    for i in range(n):
        p0, p1 = pts[i], pts[(i + 1) % n]
        e = p1 - p0
        nn = np.array([e[1], 0, -e[0]])
        nn /= max(np.linalg.norm(nn), 1e-9)
        pos = np.array([[p0[0], -half_h, p0[1]], [p1[0], -half_h, p1[1]], [p1[0], half_h, p1[1]], [p0[0], half_h, p0[1]]])
        parts.append(MeshData(pos.astype(np.float32), np.tile(nn, (4, 1)).astype(np.float32),
                              np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32), np.array([0, 2, 1, 0, 3, 2], np.uint32)))
    return merge(parts)


def crystal(sides: int = 6, height: float = 1.0) -> MeshData:
    """Hexagonal crystal prism with pointed top (files on planet surfaces)."""
    a = np.linspace(0, 2 * math.pi, sides, endpoint=False)
    ring = np.stack([np.cos(a) * 0.45, np.zeros(sides), np.sin(a) * 0.45], 1)
    bottom = ring + [0, -0.6 * height, 0]
    top = ring + [0, 0.45 * height, 0]
    tip = np.array([[0, 1.0 * height, 0]])
    base_c = np.array([[0, -0.6 * height, 0]])
    pos = np.concatenate([bottom, top, tip, base_c])
    idx = []
    for i in range(sides):
        j = (i + 1) % sides
        idx += [i, sides + j, j, i, sides + i, sides + j]
        idx += [sides + i, 2 * sides, sides + j]
        idx += [i, j, 2 * sides + 1]
    m = MeshData(pos.astype(np.float32), None, np.zeros((len(pos), 2), np.float32), np.array(idx, np.uint32))
    return flat_shaded(m)


# ---- line meshes -----------------------------------------------------------

def circle_lines(segs: int = 128) -> MeshData:
    a = np.linspace(0, 2 * math.pi, segs, endpoint=False)
    pos = np.stack([np.cos(a), np.zeros(segs), np.sin(a)], 1)
    idx = np.stack([np.arange(segs), (np.arange(segs) + 1) % segs], 1).reshape(-1)
    return MeshData(pos.astype(np.float32), None, None, idx.astype(np.uint32), LINES)


def box_edges(hx, hy, hz) -> MeshData:
    c = np.array([[x, y, z] for x in (-hx, hx) for y in (-hy, hy) for z in (-hz, hz)], np.float32)
    e = []
    for i in range(8):
        for j in range(i + 1, 8):
            if bin(i ^ j).count("1") == 1:
                e += [i, j]
    return MeshData(c, None, None, np.array(e, np.uint32), LINES)


def polyline_loop(points3: np.ndarray) -> MeshData:
    n = len(points3)
    idx = np.stack([np.arange(n), (np.arange(n) + 1) % n], 1).reshape(-1)
    return MeshData(np.asarray(points3, np.float32), None, None, idx.astype(np.uint32), LINES)


def merge_lines(meshes: list[MeshData]) -> MeshData:
    pos, idx, base = [], [], 0
    for m in meshes:
        pos.append(m.positions)
        idx.append(m.indices + base)
        base += len(m.positions)
    return MeshData(np.concatenate(pos).astype(np.float32), None, None, np.concatenate(idx).astype(np.uint32), LINES)


def quad() -> MeshData:
    pos = np.array([[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]], np.float32)
    uv = np.array([[0, 1], [1, 1], [1, 0], [0, 0]], np.float32)
    return MeshData(pos, np.tile([0, 0, 1], (4, 1)).astype(np.float32), uv, np.array([0, 1, 2, 0, 2, 3], np.uint32))
