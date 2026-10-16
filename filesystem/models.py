"""In-memory filesystem model.

Only directories the user has visited (plus their immediate children) are kept
as :class:`FSNode` trees; recursive folder sizes live in the separate,
bounded :class:`~filesystem.sizes.SizeCache`.
"""
from __future__ import annotations

import enum
from collections import OrderedDict
from dataclasses import dataclass, field

from .filetypes import category_for, extension
from .paths import norm_key


class ScanState(enum.Enum):
    UNSCANNED = "not scanned"
    SCANNING = "scanning"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class EntryInfo:
    """Result of listing one directory entry (pure data, thread-safe)."""
    name: str
    path: str
    is_dir: bool
    size: int = 0
    mtime: float | None = None
    is_link: bool = False
    hidden: bool = False
    error: str | None = None


@dataclass
class PreviewEntry:
    """Lightweight sample of a grandchild, used for level-of-detail previews."""
    name: str
    is_dir: bool
    size: int


@dataclass(eq=False)
class FSNode:
    path: str
    name: str
    is_dir: bool
    size: int = 0                      # file size (files only)
    mtime: float | None = None
    is_link: bool = False
    hidden: bool = False
    error: str | None = None
    parent: "FSNode | None" = field(default=None, repr=False)
    children: list["FSNode"] | None = None   # None => not listed yet
    list_state: ScanState = ScanState.UNSCANNED
    # recursive aggregate (directories); filled from SizeCache
    total_size: int | None = None
    file_count: int | None = None
    dir_count: int | None = None
    size_complete: bool = False
    size_errors: int = 0
    # sampled grandchildren (directories only) for LOD previews
    preview: list[PreviewEntry] | None = None
    preview_total: int = 0

    @property
    def key(self) -> str:
        return norm_key(self.path)

    @property
    def extension(self) -> str:
        return "" if self.is_dir else extension(self.name)

    @property
    def category(self) -> str:
        return "folder" if self.is_dir else category_for(self.name)

    def effective_size(self) -> int:
        """Best known size in bytes (recursive estimate for folders)."""
        if not self.is_dir:
            return self.size
        if self.total_size is not None:
            return self.total_size
        if self.children is not None:
            return sum(c.effective_size() for c in self.children)
        return 0

    def direct_counts(self) -> tuple[int, int]:
        if self.children is None:
            return (0, 0)
        dirs = sum(1 for c in self.children if c.is_dir)
        return (len(self.children) - dirs, dirs)

    @classmethod
    def from_entry(cls, e: EntryInfo, parent: "FSNode | None" = None) -> "FSNode":
        return cls(path=e.path, name=e.name, is_dir=e.is_dir, size=e.size, mtime=e.mtime,
                   is_link=e.is_link, hidden=e.hidden, error=e.error, parent=parent)


def sort_children(nodes: list[FSNode]) -> list[FSNode]:
    """Folders first, then larger first, then name (stable presentation order)."""
    return sorted(nodes, key=lambda n: (not n.is_dir, -n.effective_size(), n.name.lower()))


class FileSystemModel:
    """Registry of listed directory nodes with an LRU bound on listings."""

    def __init__(self, max_listed_dirs: int = 3000):
        self._nodes: dict[str, FSNode] = {}
        self._lru: "OrderedDict[str, None]" = OrderedDict()
        self.max_listed_dirs = max_listed_dirs

    def get(self, path: str) -> FSNode | None:
        return self._nodes.get(norm_key(path))

    def get_or_create_dir(self, path: str, name: str | None = None) -> FSNode:
        from .paths import display_name
        k = norm_key(path)
        node = self._nodes.get(k)
        if node is None:
            node = FSNode(path=path, name=name or display_name(path), is_dir=True)
            self._nodes[k] = node
        return node

    def register(self, node: FSNode) -> None:
        self._nodes[node.key] = node

    def apply_listing(self, path: str, entries: list[EntryInfo], error: str | None,
                      protected: set[str] | None = None) -> FSNode:
        """Attach a fresh listing to the directory node for *path*."""
        node = self.get_or_create_dir(path)
        old = {c.key: c for c in (node.children or [])}
        children: list[FSNode] = []
        for e in entries:
            k = norm_key(e.path)
            existing = self._nodes.get(k) if e.is_dir else None
            if existing is None:
                existing = old.get(k)
            if existing is not None and existing.is_dir == e.is_dir:
                existing.size, existing.mtime, existing.error = e.size, e.mtime, e.error
                existing.is_link, existing.hidden = e.is_link, e.hidden
                existing.parent = node
                child = existing
            else:
                child = FSNode.from_entry(e, node)
            if child.is_dir:
                self._nodes[child.key] = child
            children.append(child)
        node.children = sort_children(children)
        node.error = error
        node.list_state = ScanState.ERROR if error and not entries else ScanState.COMPLETE
        self._touch(node.key, protected or set())
        return node

    def _touch(self, key: str, protected: set[str]) -> None:
        self._lru.pop(key, None)
        self._lru[key] = None
        while len(self._lru) > self.max_listed_dirs:
            old_key, _ = self._lru.popitem(last=False)
            if old_key in protected:
                self._lru[old_key] = None
                if len(protected) >= len(self._lru):
                    break
                continue
            n = self._nodes.get(old_key)
            if n is not None:
                n.children = None
                n.preview = None
                n.list_state = ScanState.UNSCANNED

    def invalidate(self, path: str | None = None) -> None:
        """Forget listings (all, or a subtree) so they are rescanned."""
        if path is None:
            for n in self._nodes.values():
                n.children, n.preview = None, None
                n.list_state = ScanState.UNSCANNED
                n.size_complete = False
            self._lru.clear()
            return
        k = norm_key(path)
        for key, n in self._nodes.items():
            if key == k or key.startswith(k.rstrip("\\/") + "\\") or key.startswith(k.rstrip("\\/") + "/"):
                n.children, n.preview = None, None
                n.list_state = ScanState.UNSCANNED
                n.size_complete = False
                self._lru.pop(key, None)
