"""Mapping of filesystem objects to visual kinds and sizes."""
from __future__ import annotations

import math
import zlib

from .hierarchy import Level, level_for_depth, micro_variant

# ---- visual kinds (one mesh/material combination each) --------------------
K_DEVICE = "device"
K_GALAXY = "galaxy"
K_REGION = "region"
K_CLUSTER = "cluster"
K_SYSTEM = "system"
K_PLANET = "planet"
K_MOON = "moon"
K_CRATER = "crater"
K_ROCK = "rock"
K_GRAIN = "grain"
K_MICROBE = "microbe"
K_MOLECULE = "molecule"
K_ATOM = "atom"
K_QUANTUM = "quantum"
# file kinds
K_STAR = "star"
K_EXOPLANET = "exoplanet"
K_CRYSTAL = "crystal"
K_PEBBLE = "pebble"
K_PARTICLE = "particle"

_LEVEL_KIND = {
    Level.UNIVERSE: K_DEVICE, Level.GALAXY: K_GALAXY, Level.REGION: K_REGION,
    Level.CLUSTER: K_CLUSTER, Level.SYSTEM: K_SYSTEM, Level.PLANET: K_PLANET,
    Level.MOON: K_MOON, Level.CRATER: K_CRATER, Level.ROCK: K_ROCK, Level.GRAIN: K_GRAIN,
}
_MICRO_KINDS = [K_MICROBE, K_MOLECULE, K_ATOM, K_QUANTUM]

_FILE_KIND = {
    Level.UNIVERSE: K_STAR, Level.GALAXY: K_STAR, Level.REGION: K_STAR, Level.CLUSTER: K_STAR,
    Level.SYSTEM: K_EXOPLANET, Level.PLANET: K_CRYSTAL, Level.MOON: K_CRYSTAL,
    Level.CRATER: K_PEBBLE, Level.ROCK: K_PEBBLE, Level.GRAIN: K_PARTICLE, Level.MICRO: K_PARTICLE,
}

# How the children of a container at a level are arranged
LAYOUT_DEVICE = "device"      # inside the device-shaped universe shell
LAYOUT_SPIRAL = "spiral"      # along spiral arms
LAYOUT_CLOUD = "cloud"        # nebula volume
LAYOUT_GLOBULAR = "globular"  # dense ball
LAYOUT_ORBITS = "orbits"      # Keplerian orbits around a star/planet
LAYOUT_SURFACE = "surface"    # on the surface of the centre body
LAYOUT_BOWL = "bowl"          # inside a crater bowl
LAYOUT_SHELL = "shell"        # spherical shells (microscopic)


def folder_kind(depth: int) -> str:
    lvl = level_for_depth(depth)
    if lvl == Level.MICRO:
        return _MICRO_KINDS[micro_variant(depth)]
    return _LEVEL_KIND[lvl]


def file_kind(container_depth: int) -> str:
    return _FILE_KIND[level_for_depth(container_depth)]


def folder_layout(container_depth: int) -> str:
    lvl = level_for_depth(container_depth)
    return {
        Level.UNIVERSE: LAYOUT_DEVICE, Level.GALAXY: LAYOUT_SPIRAL, Level.REGION: LAYOUT_CLOUD,
        Level.CLUSTER: LAYOUT_GLOBULAR, Level.SYSTEM: LAYOUT_ORBITS, Level.PLANET: LAYOUT_ORBITS,
        Level.MOON: LAYOUT_SURFACE, Level.CRATER: LAYOUT_BOWL,
    }.get(lvl, LAYOUT_SHELL)


def file_layout(container_depth: int) -> str:
    lvl = level_for_depth(container_depth)
    return {
        Level.UNIVERSE: LAYOUT_DEVICE, Level.GALAXY: LAYOUT_SPIRAL, Level.REGION: LAYOUT_CLOUD,
        Level.CLUSTER: LAYOUT_GLOBULAR, Level.SYSTEM: LAYOUT_ORBITS, Level.PLANET: LAYOUT_SURFACE,
        Level.MOON: LAYOUT_SURFACE, Level.CRATER: LAYOUT_BOWL,
    }.get(lvl, LAYOUT_SHELL)


# ---- size scaling ------------------------------------------------------------
MIN_FILE_RADIUS = 0.10
MIN_FOLDER_RADIUS = 0.28


def visual_radius(size_bytes: int | float | None, is_dir: bool = False) -> float:
    """Nonlinear (logarithmic-exponential) size -> radius in scene units.

    1 KB ~ 0.28, 1 MB ~ 0.64, 100 MB ~ 1.1, 1 GB ~ 1.46, 100 GB ~ 2.5, 1 TB ~ 3.4.
    Monotonic, so larger data is always at least as large on screen.
    """
    s = math.log10(max(float(size_bytes or 0), 1.0))
    r = 0.12 * (1.32 ** s)
    return max(r, MIN_FOLDER_RADIUS if is_dir else MIN_FILE_RADIUS)


def stable_seed(text: str) -> int:
    """Deterministic per-name seed so a folder always looks/places the same."""
    return zlib.crc32(text.lower().encode("utf-8", "surrogatepass"))


def seed_unit(text: str, salt: int = 0) -> float:
    return ((stable_seed(text) ^ (salt * 0x9E3779B1)) & 0xFFFFFF) / float(0xFFFFFF)


def format_size(n: int | float | None) -> str:
    if n is None:
        return "unknown"
    n = float(n)
    for unit in ("bytes", "KB", "MB", "GB", "TB", "PB"):
        if n < 1024 or unit == "PB":
            if unit == "bytes":
                return f"{int(n):,} bytes"
            return f"{n:.1f} {unit}" if n < 100 else f"{n:.0f} {unit}"
        n /= 1024.0
    return f"{n:.0f} PB"
