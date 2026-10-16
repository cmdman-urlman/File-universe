"""Builds renderable scenes from the filesystem model (no OpenGL here)."""
from __future__ import annotations

import math

import numpy as np

from filesystem.filetypes import CATEGORY_COLORS, PREVIEWABLE_IMAGES
from filesystem.models import FSNode
from objects.devices import SHELL_COLORS, default_half
from objects.registry import KINDS
from rendering.scene import Scene, SceneItem

from . import procedural_generation as pg
from .hierarchy import Level, level_for_depth
from .mapping import (K_CRATER, K_DEVICE, LAYOUT_BOWL, LAYOUT_CLOUD, LAYOUT_DEVICE, LAYOUT_GLOBULAR, LAYOUT_ORBITS,
                      LAYOUT_SPIRAL, LAYOUT_SURFACE, file_kind, file_layout, folder_kind,
                      folder_layout, seed_unit, visual_radius)

MAX_RENDERED_CHILDREN = 20_000
MAX_SATELLITES_PER_CHILD = 18
MAX_SATELLITE_PARENTS = 400


def icon_key_for(node: FSNode) -> str:
    return ("dir:" if node.is_dir else "file:") + node.path


def _item_color(item: SceneItem, seed: float) -> tuple[float, float, float]:
    spec = KINDS.get(item.kind)
    base = spec.palette(seed) if spec else (0.8, 0.8, 0.8)
    if item.is_dir or item.is_center:
        return base
    cat = CATEGORY_COLORS.get(item.category, CATEGORY_COLORS["other"])
    w = 0.7
    return tuple(cat[i] * w + base[i] * (1 - w) for i in range(3))


def _alloc(sc: Scene, n: int) -> None:
    sc.base_pos = np.zeros((n, 3), np.float32)
    sc.target_pos = np.zeros((n, 3), np.float32)
    sc.orbit_w = np.zeros(n, np.float32)
    sc.radius = np.zeros(n, np.float32)
    sc.radius_target = np.zeros(n, np.float32)
    sc.color = np.ones((n, 4), np.float32)
    sc.seed = np.zeros(n, np.float32)
    sc.style = np.zeros(n, np.float32)
    sc.tilt = np.zeros((n, 2), np.float32)
    sc.spin = np.zeros(n, np.float32)
    sc.squash = np.ones(n, np.float32)
    sc.alpha = np.zeros(n, np.float32)
    sc.alpha_target = np.ones(n, np.float32)
    sc.emissive = np.zeros(n, np.float32)
    sc.rings = np.zeros(n, bool)


def _fill_appearance(sc: Scene) -> None:
    for i, it in enumerate(sc.items):
        key = it.payload.path if hasattr(it.payload, "path") else it.label
        s = seed_unit(key)
        sc.seed[i] = s
        spec = KINDS.get(it.kind)
        sc.color[i, :3] = _item_color(it, s)
        if spec is not None:
            sc.style[i] = spec.style_of(s)
            sc.emissive[i] = spec.emissive
            ring_thr = spec.extra.get("ring_threshold")
            sc.rings[i] = spec.lines is not None and (ring_thr is None or s > ring_thr)
        # axial tilts / inclinations so things do not look flat and identical
        if it.kind in ("galaxy", "region", "cluster"):
            sc.tilt[i] = ((seed_unit(key, 2) - 0.5) * 0.9, (seed_unit(key, 3) - 0.5) * 0.9)
            sc.spin[i] = 0.04 + 0.05 * seed_unit(key, 4)
        elif it.kind in ("planet", "exoplanet", "moon", "system", "star", "atom", "quantum", "molecule", "microbe"):
            sc.tilt[i] = ((seed_unit(key, 2) - 0.5) * 0.6, (seed_unit(key, 3) - 0.5) * 0.6)
            sc.spin[i] = 0.08 + 0.25 * seed_unit(key, 4)
        elif it.kind in ("rock", "grain", "pebble", "particle"):
            sc.tilt[i] = (seed_unit(key, 2) * 6.28, seed_unit(key, 3) * 6.28)
            sc.spin[i] = 0.05 * seed_unit(key, 4)


# ---- folder scenes ----------------------------------------------------------

def build_folder_scene(node: FSNode, depth: int, device_kind: str = "ssd") -> Scene:
    children = node.children or []
    shown = children[:MAX_RENDERED_CHILDREN]
    sc = Scene(title=node.name, payload=node, depth=depth, device_kind=device_kind)
    sc.hidden_count = max(0, len(children) - len(shown))
    center_kind = folder_kind(depth)
    sc.items.append(SceneItem(node.name, center_kind, node, True, True, "folder",
                              icon_key_for(node), drawn=center_kind != K_DEVICE))
    for c in shown:
        kind = folder_kind(depth + 1) if c.is_dir else file_kind(depth)
        img = c.path if (not c.is_dir and c.extension in PREVIEWABLE_IMAGES and kind == "exoplanet") else None
        sc.items.append(SceneItem(c.name, kind, c, c.is_dir, False, c.category, icon_key_for(c), img))
    _alloc(sc, len(sc.items))
    _fill_appearance(sc)
    sc.nebula_hue = seed_unit(node.path, 9)
    lvl = level_for_depth(depth)
    sc.star_light = lvl in (Level.SYSTEM,)
    sc.tilt[0] = 0.0          # the centre body defines the scene plane
    layout_folder_scene(sc)
    sc.base_pos[:] = sc.target_pos
    sc.radius[:] = sc.radius_target
    sc.alpha[0] = 1.0
    _build_satellites(sc, depth)
    return sc


UNMEASURED_FOLDER_RADIUS = 0.42


def _radius_of(node: FSNode, is_dir: bool) -> float:
    if is_dir and node.total_size is None:
        return UNMEASURED_FOLDER_RADIUS        # placeholder until the size is known
    return visual_radius(node.effective_size(), is_dir)


def _radii_for(items: list[SceneItem]) -> np.ndarray:
    return np.array([_radius_of(it.payload, it.is_dir) for it in items], np.float64)


def layout_folder_scene(sc: Scene) -> None:
    """(Re)compute radii and positions; called again when folder sizes arrive."""
    node: FSNode = sc.payload
    depth = sc.depth
    lvl = level_for_depth(depth)
    n = len(sc.items)
    kids = sc.items[1:]
    radii = _radii_for(kids) if kids else np.zeros(0)
    seeds = sc.seed[1:].astype(np.float64)
    pos = np.zeros((n - 1, 3), np.float32)
    w = np.zeros(n - 1, np.float32)
    total_r = visual_radius(node.effective_size(), True)
    center_r = total_r
    sc.orbit_rings, sc.belts, sc.shell = [], [], None
    is_dir = np.array([k.is_dir for k in kids], bool)
    fl, fil = folder_layout(depth), file_layout(depth)

    if fl == LAYOUT_DEVICE:
        lay, half = pg.device_layout(radii, seeds, sc.device_kind or "ssd")
        pos, extent = lay.positions, max(lay.extent, max(half[0], half[2]))
        sc.shell = (sc.device_kind or "ssd", half, SHELL_COLORS.get(sc.device_kind or "ssd", (0.6, 0.8, 1.0)))
        center_r = max(half)
    elif fl == LAYOUT_SPIRAL:
        lay = pg.vogel_disk(radii, seeds, inner=1.5, packing=2.7, arms=3, twist=3.2, thickness=1.2, jitter=0.35)
        pos, extent = lay.positions, lay.extent
        center_r = max(extent * 1.05, 4.0)
    elif fl == LAYOUT_CLOUD:
        lay = pg.ball(radii, seeds, inner=1.0, packing=2.6, squash=0.6)
        pos, extent = lay.positions, lay.extent
        center_r = max(extent * 1.1, 4.0)
    elif fl == LAYOUT_GLOBULAR:
        lay = pg.ball(radii, seeds, inner=1.2, packing=2.9)
        pos, extent = lay.positions, lay.extent
        center_r = max(extent * 0.9, 3.0)
    elif fl == LAYOUT_ORBITS and fil == LAYOUT_ORBITS:          # planetary system
        center_r = min(max(total_r * 1.3, 0.9), 3.5)
        lay = pg.orbits(radii, seeds, inner=center_r * 1.6)
        pos, w, extent = lay.positions, lay.orbit_speed, lay.extent
        sc.orbit_rings = [float(r) for r in lay.extra.get("rings", [])]
        if "belt" in lay.extra:
            sc.belts.append(lay.extra["belt"])
    elif fl == LAYOUT_ORBITS:                                   # planet: moons orbit, files on surface
        files_idx = np.where(~is_dir)[0]
        dirs_idx = np.where(is_dir)[0]
        center_r = pg.surface_radius_needed(radii[files_idx], max(total_r * 1.6, 1.5))
        surf = pg.surface(radii[files_idx], seeds[files_idx], center_r, embed=0.45)
        pos[files_idx] = surf.positions
        if len(files_idx):
            a, b = pg.orientation_from_normals(surf.normals)
            sc.tilt[1 + files_idx, 0], sc.tilt[1 + files_idx, 1] = a, b
        orb = pg.orbits(radii[dirs_idx], seeds[dirs_idx], inner=center_r * 1.5, speed=0.25)
        pos[dirs_idx] = orb.positions
        w[dirs_idx] = orb.orbit_speed
        sc.orbit_rings = [float(r) for r in orb.extra.get("rings", [])]
        if "belt" in orb.extra:
            sc.belts.append(orb.extra["belt"])
        extent = max(surf.extent, orb.extent, center_r)
    elif fl == LAYOUT_SURFACE:                                  # moon: craters + crystals on the surface
        crater = np.array([k.kind == K_CRATER for k in kids], bool)
        base = max(total_r * 1.6, 1.5, 2.8 * float(radii[crater].max()) if crater.any() else 0.0)
        center_r = pg.surface_radius_needed(radii, base, packing=2.4)
        lay = pg.surface(radii, seeds, center_r, embed=0.45)
        pos = lay.positions.copy()
        sc.squash[1:] = 1.0
        if crater.any():
            pos[crater] = lay.normals[crater] * center_r
            sc.squash[1 + np.nonzero(crater)[0]] = -center_r
        if len(kids):
            a, b = pg.orientation_from_normals(lay.normals)
            sc.tilt[1:, 0], sc.tilt[1:, 1] = a, b
        extent = max(lay.extent, center_r)
    elif fl == LAYOUT_BOWL:
        lay, crater_r = pg.bowl(radii, seeds, max(total_r * 2.0, 2.5))
        pos, extent, center_r = lay.positions, max(lay.extent, crater_r * 1.35), crater_r
    else:                                                      # LAYOUT_SHELL (rock and deeper)
        center_r = max(total_r * 1.4, 1.0)
        lay = pg.ball(radii, seeds, inner=center_r * 1.7, packing=3.0)
        pos, extent = lay.positions, lay.extent
        w = np.full(n - 1, 0.03, np.float32)
    sc.target_pos[1:] = pos
    sc.orbit_w[1:] = w
    sc.radius_target[1:] = radii
    sc.radius_target[0] = center_r
    sc.extent = max(float(extent), center_r, 2.0)
    sc.view_distance = max(sc.extent * 2.1, center_r * 3.6)
    sc.alpha[0] = 1.0
    # backdrop-like centres are drawn translucent so children stay visible
    if lvl in (Level.GALAXY, Level.REGION, Level.CLUSTER):
        sc.color[0, 3] = 0.55


def _build_satellites(sc: Scene, depth: int) -> None:
    parents, offsets, rel, colors, kinds, styles, seeds = [], [], [], [], [], [], []
    count = 0
    for i, it in enumerate(sc.items):
        if i == 0 or not it.is_dir:
            continue
        prev = getattr(it.payload, "preview", None)
        if not prev:
            continue
        count += 1
        if count > MAX_SATELLITE_PARENTS:
            break
        sample = prev[:MAX_SATELLITES_PER_CHILD]
        off = pg.satellite_offsets(len(sample), 1.0, float(sc.seed[i]))
        for j, pe in enumerate(sample):
            kind = folder_kind(depth + 2) if pe.is_dir else file_kind(depth + 1)
            spec = KINDS.get(kind)
            s = seed_unit(it.payload.path + "/" + pe.name)
            parents.append(i)
            offsets.append(off[j])
            size_f = math.log10(max(pe.size, 1)) / 12.0
            rel.append((0.16 if pe.is_dir else 0.08) + 0.14 * size_f)
            if pe.is_dir:
                rgb = spec.palette(s) if spec else (0.8, 0.8, 0.8)
            else:
                from filesystem.filetypes import category_for
                rgb = CATEGORY_COLORS.get(category_for(pe.name), CATEGORY_COLORS["other"])
            colors.append((*rgb, 1.0))
            kinds.append(kind)
            styles.append(spec.style_of(s) if spec else 8)
            seeds.append(s)
    if not parents:
        return
    sc.sat_parent = np.array(parents, np.int32)
    sc.sat_offset = np.array(offsets, np.float32)
    sc.sat_radius = np.array(rel, np.float32)
    sc.sat_color = np.array(colors, np.float32)
    sc.sat_kind = kinds
    sc.sat_style = np.array(styles, np.float32)
    sc.sat_seed = np.array(seeds, np.float32)


def refresh_satellites(sc: Scene) -> None:
    _build_satellites(sc, sc.depth)


# ---- home (multiverse) scene ----------------------------------------------

def device_scale(total: int | None) -> float:
    gb = max((total or 0) / 1e9, 1.0)
    return 0.8 + 0.22 * math.log10(gb)


def build_home_scene(devices: list) -> Scene:
    sc = Scene(title="This PC", payload=None, depth=-1)
    shown = [d for d in devices if d.ready] + [d for d in devices if not d.ready]
    for d in shown:
        sc.items.append(SceneItem(d.title, "device:" + d.kind, d, True, False, "drive", "drive:" + d.mount))
    n = len(sc.items)
    _alloc(sc, n)
    scales = np.array([device_scale(d.total) for d in shown], np.float32)
    x = 0.0
    xs = []
    for i, d in enumerate(shown):
        hx, hy, hz = default_half(d.kind, float(scales[i]))
        x += hx
        xs.append(x)
        x += hx + 2.5
        sc.radius_target[i] = math.sqrt(hx * hx + hz * hz)
        rgb = SHELL_COLORS.get(d.kind, (0.8, 0.8, 0.8))
        sc.color[i] = (*rgb, 1.0 if d.ready else 0.35)
        sc.seed[i] = seed_unit(d.mount)
    if xs:
        off = (xs[0] + xs[-1]) / 2
        sc.target_pos[:, 0] = np.array(xs) - off
    sc.base_pos[:] = sc.target_pos
    sc.radius[:] = sc.radius_target
    sc.extra["device_scale"] = scales
    sc.extent = max(x / 2, 6.0)
    sc.view_distance = sc.extent * 1.9 + 4
    sc.nebula_hue = 0.62
    # a galaxy swirling inside each ready device-universe
    ready = [i for i, d in enumerate(shown) if d.ready]
    if ready:
        sc.sat_parent = np.array(ready, np.int32)
        sc.sat_offset = np.zeros((len(ready), 3), np.float32)
        sc.sat_radius = np.full(len(ready), 0.55, np.float32)
        sc.sat_color = np.array([(*KINDS["galaxy"].palette(seed_unit(shown[i].mount)), 1.0) for i in ready], np.float32)
        sc.sat_kind = ["galaxy"] * len(ready)
        sc.sat_style = np.zeros(len(ready), np.float32)
        sc.sat_seed = np.array([seed_unit(shown[i].mount) for i in ready], np.float32)
    return sc
