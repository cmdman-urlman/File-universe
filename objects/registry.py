"""Registry of all object kinds by name."""
from __future__ import annotations

from .base import KindSpec
from .crater import CRATER
from .galaxy import GALAXY, REGION
from .microscopic_objects import ATOM, CRYSTAL, GRAIN, MICROBE, MOLECULE, PARTICLE, PEBBLE, QUANTUM, ROCK
from .moon import MOON
from .planet import EXOPLANET, PLANET
from .planetary_system import FILE_STAR, SYSTEM
from .star_cluster import CLUSTER

KINDS: dict[str, KindSpec] = {k.kind: k for k in (
    GALAXY, REGION, CLUSTER, SYSTEM, PLANET, MOON, CRATER, ROCK, GRAIN, MICROBE, MOLECULE, ATOM, QUANTUM,
    FILE_STAR, EXOPLANET, CRYSTAL, PEBBLE, PARTICLE,
)}


def get_kind(name: str) -> KindSpec:
    return KINDS[name]
