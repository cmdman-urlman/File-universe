"""Read-only directory listing primitives (safe to call from worker threads).

Nothing in this module opens file contents; it only enumerates directory
entries and reads their metadata via ``os.scandir`` (whose ``stat`` results are
served from the directory enumeration itself on Windows, so listing is fast).
"""
from __future__ import annotations

import os
import stat as stat_mod

from .models import EntryInfo, PreviewEntry
from .paths import os_path

MAX_LIST_ENTRIES = 100_000
FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def describe_error(exc: BaseException) -> str:
    if isinstance(exc, PermissionError):
        return "Access denied"
    if isinstance(exc, FileNotFoundError):
        return "Not found (removed or disconnected)"
    if isinstance(exc, NotADirectoryError):
        return "Not a directory"
    if isinstance(exc, OSError) and exc.strerror:
        return exc.strerror
    return str(exc) or exc.__class__.__name__


def is_link_entry(entry: os.DirEntry) -> bool:
    """True for symlinks, junctions and mount points; these are never descended."""
    try:
        if entry.is_symlink():
            return True
        if hasattr(entry, "is_junction") and entry.is_junction():
            return True
    except OSError:
        return True
    return False


def entry_info(entry: os.DirEntry, parent_display: str) -> EntryInfo:
    path = os.path.join(parent_display, entry.name)
    try:
        link = is_link_entry(entry)
        is_dir = entry.is_dir(follow_symlinks=True) if link else entry.is_dir(follow_symlinks=False)
    except OSError as exc:
        return EntryInfo(entry.name, path, False, error=describe_error(exc))
    try:
        st = entry.stat(follow_symlinks=False)
        size = 0 if is_dir or link else st.st_size
        attrs = getattr(st, "st_file_attributes", 0)
        hidden = bool(attrs & FILE_ATTRIBUTE_HIDDEN) or entry.name.startswith(".")
        return EntryInfo(entry.name, path, is_dir, size, st.st_mtime, link, hidden)
    except OSError as exc:
        return EntryInfo(entry.name, path, is_dir, is_link=link, error=describe_error(exc))


def list_directory(path: str, max_entries: int = MAX_LIST_ENTRIES,
                   cancel=None) -> tuple[list[EntryInfo], str | None]:
    """List one directory. Returns (entries, error-message-or-None)."""
    entries: list[EntryInfo] = []
    error = None
    try:
        with os.scandir(os_path(path)) as it:
            for entry in it:
                if cancel is not None and cancel.is_set():
                    return entries, "Cancelled"
                entries.append(entry_info(entry, path))
                if len(entries) >= max_entries:
                    error = f"Very large folder: showing the first {max_entries:,} entries"
                    break
    except OSError as exc:
        error = describe_error(exc)
    return entries, error


def sample_directory(path: str, limit: int = 48, count_limit: int = 5000) -> tuple[list[PreviewEntry], int]:
    """Cheap shallow sample of a folder's contents for LOD previews."""
    sample: list[PreviewEntry] = []
    total = 0
    try:
        with os.scandir(os_path(path)) as it:
            for entry in it:
                total += 1
                if len(sample) < limit:
                    try:
                        is_dir = entry.is_dir(follow_symlinks=False)
                        size = 0 if is_dir else entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        is_dir, size = False, 0
                    sample.append(PreviewEntry(entry.name, is_dir, size))
                if total >= count_limit:
                    break
    except OSError:
        pass
    return sample, total


def stat_path(path: str) -> EntryInfo | None:
    """Metadata for a single path (used for drive roots and search hits)."""
    try:
        st = os.stat(os_path(path), follow_symlinks=False)
    except OSError as exc:
        name = os.path.basename(path.rstrip("\\/")) or path
        return EntryInfo(name, path, os.path.isdir(os_path(path)), error=describe_error(exc))
    is_dir = stat_mod.S_ISDIR(st.st_mode)
    name = os.path.basename(path.rstrip("\\/")) or path
    return EntryInfo(name, path, is_dir, 0 if is_dir else st.st_size, st.st_mtime,
                     stat_mod.S_ISLNK(st.st_mode))
