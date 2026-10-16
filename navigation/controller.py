"""Navigation history (back / forward / up / home) independent of the UI."""
from __future__ import annotations

from dataclasses import dataclass

from filesystem.paths import is_ancestor, norm_key, parent_path

HOME = None   # the "This PC" multiverse


@dataclass(frozen=True)
class Location:
    path: str | None          # None = home
    mount: str | None = None  # drive mount the path belongs to

    @property
    def is_home(self) -> bool:
        return self.path is None

    @property
    def key(self) -> str:
        return "" if self.path is None else norm_key(self.path)


def transition_mode(old: Location | None, new: Location) -> str:
    """'in' when new is a direct child of old, 'out' for the direct parent, else 'jump'."""
    if old is None:
        return "jump"
    if old.is_home and not new.is_home:
        return "in"
    if new.is_home and not old.is_home:
        return "out"
    if old.is_home and new.is_home:
        return "refresh"
    if old.key == new.key:
        return "refresh"
    if is_ancestor(old.path, new.path) and parent_path(new.path) and norm_key(parent_path(new.path)) == old.key:
        return "in"
    if is_ancestor(new.path, old.path) and parent_path(old.path) and norm_key(parent_path(old.path)) == new.key:
        return "out"
    return "jump"


class History:
    def __init__(self, max_len: int = 200):
        self._items: list[Location] = []
        self._index = -1
        self.max_len = max_len

    @property
    def current(self) -> Location | None:
        return self._items[self._index] if 0 <= self._index < len(self._items) else None

    def push(self, loc: Location) -> None:
        cur = self.current
        if cur is not None and cur.key == loc.key and cur.is_home == loc.is_home:
            return
        del self._items[self._index + 1:]
        self._items.append(loc)
        if len(self._items) > self.max_len:
            self._items.pop(0)
        self._index = len(self._items) - 1

    def can_back(self) -> bool:
        return self._index > 0

    def can_forward(self) -> bool:
        return self._index < len(self._items) - 1

    def back(self) -> Location | None:
        if not self.can_back():
            return None
        self._index -= 1
        return self.current

    def forward(self) -> Location | None:
        if not self.can_forward():
            return None
        self._index += 1
        return self.current

    def replace_missing(self, valid_mounts: set[str]) -> None:
        """Drop history entries on drives that disappeared."""
        keep = [l for l in self._items if l.is_home or (l.mount or "").upper() in valid_mounts]
        if len(keep) != len(self._items):
            cur = self.current
            self._items = keep or [Location(None)]
            self._index = len(self._items) - 1
            if cur in self._items:
                self._index = self._items.index(cur)
