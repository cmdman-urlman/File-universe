"""Recursive folder size calculation with caching and cancellation.

Sizes are computed by an iterative post-order walk (no recursion limit, any
depth). Every completed sub-directory result is cached, keyed by path and
validated by the directory's modification time, so navigating deeper later
does not rescan what has already been measured. Symbolic links, junctions and
mount points are never followed, which also rules out directory cycles.
"""
from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

from .paths import norm_key, os_path
from .scanner import is_link_entry

MAX_WALK_DEPTH = 1024


@dataclass
class SizeResult:
    total: int = 0
    files: int = 0
    dirs: int = 0
    errors: int = 0            # inaccessible folders/entries skipped
    complete: bool = True      # False if cancelled before finishing

    def add_child(self, other: "SizeResult") -> None:
        self.total += other.total
        self.files += other.files
        self.dirs += other.dirs + 1
        self.errors += other.errors
        self.complete = self.complete and other.complete


class SizeCache:
    """Thread-safe bounded LRU of completed directory sizes."""

    def __init__(self, max_entries: int = 400_000):
        self._data: "OrderedDict[str, tuple[SizeResult, float | None]]" = OrderedDict()
        self._lock = threading.Lock()
        self.max_entries = max_entries

    def get(self, path: str, mtime: float | None = None) -> SizeResult | None:
        k = norm_key(path)
        with self._lock:
            item = self._data.get(k)
            if item is None:
                return None
            res, cached_mtime = item
            if mtime is not None and cached_mtime is not None and abs(cached_mtime - mtime) > 1e-6:
                del self._data[k]
                return None
            self._data.move_to_end(k)
            return res

    def put(self, path: str, result: SizeResult, mtime: float | None) -> None:
        if not result.complete:
            return
        k = norm_key(path)
        with self._lock:
            self._data[k] = (result, mtime)
            self._data.move_to_end(k)
            while len(self._data) > self.max_entries:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        return len(self._data)


class _Frame:
    __slots__ = ("path", "mtime", "pending", "result")

    def __init__(self, path: str, mtime: float | None):
        self.path = path
        self.mtime = mtime
        self.pending: list[tuple[str, float | None]] = []
        self.result = SizeResult()


def _open_frame(path: str, mtime: float | None) -> _Frame:
    frame = _Frame(path, mtime)
    try:
        with os.scandir(os_path(path)) as it:
            for entry in it:
                try:
                    if is_link_entry(entry):
                        frame.result.files += 1          # the link itself, never followed
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        try:
                            m = entry.stat(follow_symlinks=False).st_mtime
                        except OSError:
                            m = None
                        frame.pending.append((os.path.join(path, entry.name), m))
                    else:
                        frame.result.files += 1
                        frame.result.total += entry.stat(follow_symlinks=False).st_size
                except OSError:
                    frame.result.errors += 1
    except OSError:
        frame.result.errors += 1
    return frame


def compute_tree_size(root: str, cancel: threading.Event | None = None,
                      cache: SizeCache | None = None, progress=None,
                      progress_interval: float = 0.3, root_mtime: float | None = None) -> SizeResult:
    """Total size of *root* including all descendants.

    ``progress(partial: SizeResult, current_path)`` is called periodically with
    a running estimate. On cancellation a partial result with
    ``complete=False`` is returned.
    """
    if cache is not None:
        hit = cache.get(root, root_mtime)
        if hit is not None:
            return hit
    stack = [_open_frame(root, root_mtime)]
    last_report = time.monotonic()
    while stack:
        if cancel is not None and cancel.is_set():
            partial = SizeResult(complete=False)
            for f in stack:
                partial.total += f.result.total
                partial.files += f.result.files
                partial.dirs += f.result.dirs
                partial.errors += f.result.errors
            return partial
        top = stack[-1]
        if top.pending:
            sub_path, sub_mtime = top.pending.pop()
            hit = cache.get(sub_path, sub_mtime) if cache is not None else None
            if hit is not None:
                top.result.add_child(hit)
            elif len(stack) >= MAX_WALK_DEPTH:
                top.result.errors += 1
            else:
                stack.append(_open_frame(sub_path, sub_mtime))
        else:
            stack.pop()
            if cache is not None:
                cache.put(top.path, top.result, top.mtime)
            if stack:
                stack[-1].result.add_child(top.result)
            else:
                return top.result
        if progress is not None:
            now = time.monotonic()
            if now - last_report >= progress_interval:
                last_report = now
                partial = SizeResult(complete=False)
                for f in stack:
                    partial.total += f.result.total
                    partial.files += f.result.files
                    partial.dirs += f.result.dirs
                progress(partial, stack[-1].path if stack else root)
    return SizeResult()
