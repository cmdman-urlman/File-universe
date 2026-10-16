"""Path helpers: normalisation keys, long-path support and display names.

All filesystem access in the application goes through :func:`os_path` so that
paths longer than MAX_PATH work on Windows even when the registry
"LongPathsEnabled" switch is off.
"""
from __future__ import annotations

import os
import sys

IS_WINDOWS = sys.platform == "win32"
_LONG_PREFIX = "\\\\?\\"
_UNC_LONG_PREFIX = "\\\\?\\UNC\\"


def strip_long_prefix(path: str) -> str:
    if path.startswith(_UNC_LONG_PREFIX):
        return "\\\\" + path[len(_UNC_LONG_PREFIX):]
    if path.startswith(_LONG_PREFIX):
        return path[len(_LONG_PREFIX):]
    return path


def os_path(path: str) -> str:
    """Return a path usable with os.* calls (adds \\\\?\\ for long Windows paths)."""
    if not IS_WINDOWS or len(path) < 240 or path.startswith(_LONG_PREFIX):
        return path
    path = os.path.abspath(path)
    if path.startswith("\\\\"):
        return _UNC_LONG_PREFIX + path[2:]
    return _LONG_PREFIX + path


def norm_key(path: str) -> str:
    """Case-insensitive (on Windows) canonical key for dictionaries."""
    p = strip_long_prefix(path)
    p = os.path.normpath(p)
    if IS_WINDOWS and len(p) == 2 and p[1] == ":":
        p += "\\"
    return os.path.normcase(p)


def display_name(path: str) -> str:
    p = strip_long_prefix(path).rstrip("\\/")
    name = os.path.basename(p)
    return name or p or path


def parent_path(path: str) -> str | None:
    p = os.path.normpath(strip_long_prefix(path))
    parent = os.path.dirname(p)
    if not parent or norm_key(parent) == norm_key(p):
        return None
    return parent


def drive_root(path: str) -> str:
    p = os.path.normpath(strip_long_prefix(path))
    drive, _ = os.path.splitdrive(p)
    if drive:
        return drive + os.sep
    return os.sep


def split_ancestors(path: str) -> list[str]:
    """Return [root, ..., path] (each ancestor as a full path)."""
    out: list[str] = []
    cur: str | None = os.path.normpath(strip_long_prefix(path))
    while cur:
        out.append(cur)
        cur = parent_path(cur)
    out.reverse()
    if out and IS_WINDOWS and len(out[0]) == 2 and out[0][1] == ":":
        out[0] += "\\"
    return out


def is_ancestor(ancestor: str, path: str) -> bool:
    a = norm_key(ancestor).rstrip("\\/")
    p = norm_key(path).rstrip("\\/")
    if a == p:
        return False
    return p.startswith(a + os.sep) or (a.endswith(":") and p.startswith(a))


def depth_below(root: str, path: str) -> int:
    """Number of path components between drive root and path (root -> 0)."""
    r = split_ancestors(root)
    p = split_ancestors(path)
    return max(0, len(p) - len(r))
