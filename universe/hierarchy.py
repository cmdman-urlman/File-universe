"""The cosmic hierarchy: which cosmic structure represents a folder at depth N.

Depth 0 is a drive root (a universe). Depths beyond the named levels continue
indefinitely as microscopic structures whose variant cycles, so there is no
maximum folder depth.
"""
from __future__ import annotations

import enum


class Level(enum.IntEnum):
    UNIVERSE = 0
    GALAXY = 1
    REGION = 2
    CLUSTER = 3
    SYSTEM = 4
    PLANET = 5
    MOON = 6
    CRATER = 7
    ROCK = 8
    GRAIN = 9
    MICRO = 10


LEVEL_NAMES = {
    Level.UNIVERSE: "Universe",
    Level.GALAXY: "Galaxy",
    Level.REGION: "Galaxy region (nebula)",
    Level.CLUSTER: "Star cluster",
    Level.SYSTEM: "Planetary system",
    Level.PLANET: "Planet",
    Level.MOON: "Moon",
    Level.CRATER: "Crater",
    Level.ROCK: "Rock",
    Level.GRAIN: "Sand grain",
}

MICRO_VARIANTS = ["Microbe", "Molecule", "Atom", "Quantum particle"]


def level_for_depth(depth: int) -> Level:
    if depth <= 0:
        return Level.UNIVERSE
    return Level(min(depth, int(Level.MICRO)))


def micro_variant(depth: int) -> int:
    """Variant index for microscopic levels (cycles forever)."""
    return max(0, depth - int(Level.MICRO)) % len(MICRO_VARIANTS)


def cosmic_name(depth: int) -> str:
    lvl = level_for_depth(depth)
    if lvl != Level.MICRO:
        return LEVEL_NAMES[lvl]
    cycle = (depth - int(Level.MICRO)) // len(MICRO_VARIANTS)
    name = MICRO_VARIANTS[micro_variant(depth)]
    return f"{name} (scale -{cycle + 1})" if cycle else name


# What files look like inside a container at a given level
FILE_KIND_NAMES = {
    Level.UNIVERSE: "Star",
    Level.GALAXY: "Star",
    Level.REGION: "Star",
    Level.CLUSTER: "Star",
    Level.SYSTEM: "Exoplanet",
    Level.PLANET: "Surface crystal",
    Level.MOON: "Surface crystal",
    Level.CRATER: "Pebble",
    Level.ROCK: "Pebble",
    Level.GRAIN: "Particle",
    Level.MICRO: "Particle",
}


def file_cosmic_name(container_depth: int) -> str:
    return FILE_KIND_NAMES[level_for_depth(container_depth)]
