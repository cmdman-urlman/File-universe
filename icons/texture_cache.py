"""Slot allocation for the icon texture atlas (pure Python, GL-free, testable)."""
from __future__ import annotations

from collections import OrderedDict


class AtlasAllocator:
    """Fixed grid of square cells with LRU eviction; pinned keys never evicted."""

    def __init__(self, atlas_size: int = 2048, cell: int = 64):
        self.atlas_size = atlas_size
        self.cell = cell
        self.per_row = atlas_size // cell
        self.capacity = self.per_row * self.per_row
        self._slots: "OrderedDict[str, int]" = OrderedDict()
        self._free = list(range(self.capacity - 1, -1, -1))
        self._pinned: set[str] = set()

    def __contains__(self, key: str) -> bool:
        return key in self._slots

    def __len__(self) -> int:
        return len(self._slots)

    def get(self, key: str) -> int | None:
        slot = self._slots.get(key)
        if slot is not None:
            self._slots.move_to_end(key)
        return slot

    def allocate(self, key: str, pinned: bool = False) -> tuple[int, str | None]:
        """Return (slot, evicted_key_or_None)."""
        if key in self._slots:
            self._slots.move_to_end(key)
            return self._slots[key], None
        evicted = None
        if not self._free:
            for old in self._slots:
                if old not in self._pinned:
                    evicted = old
                    break
            if evicted is None:
                raise RuntimeError("atlas full of pinned icons")
            self._free.append(self._slots.pop(evicted))
        slot = self._free.pop()
        self._slots[key] = slot
        if pinned:
            self._pinned.add(key)
        return slot, evicted

    def cell_origin(self, slot: int) -> tuple[int, int]:
        return (slot % self.per_row) * self.cell, (slot // self.per_row) * self.cell

    def uv_rect(self, slot: int, pad: int = 1) -> tuple[float, float, float, float]:
        x, y = self.cell_origin(slot)
        s = float(self.atlas_size)
        return ((x + pad) / s, (y + pad) / s, (x + self.cell - pad) / s, (y + self.cell - pad) / s)
