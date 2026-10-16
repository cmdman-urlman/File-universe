"""Background-friendly name search over a directory subtree."""
from __future__ import annotations

import fnmatch
import os
import threading
from collections import deque
from dataclasses import dataclass

from .paths import os_path
from .scanner import is_link_entry


@dataclass
class SearchHit:
    name: str
    path: str
    is_dir: bool
    size: int


def make_matcher(query: str):
    q = query.strip().lower()
    if not q:
        return lambda name: False
    if any(ch in q for ch in "*?["):
        return lambda name: fnmatch.fnmatchcase(name.lower(), q)
    return lambda name: q in name.lower()


def search_tree(root: str, query: str, cancel: threading.Event | None = None,
                on_batch=None, max_results: int = 5000, batch_size: int = 50,
                on_progress=None) -> list[SearchHit]:
    """Breadth-first search for names matching *query* below *root*.

    Wildcards (``*``, ``?``) are supported; otherwise a case-insensitive
    substring match is used. Links/junctions are not followed.
    """
    match = make_matcher(query)
    hits: list[SearchHit] = []
    batch: list[SearchHit] = []
    queue = deque([root])
    scanned = 0
    while queue:
        if cancel is not None and cancel.is_set():
            break
        current = queue.popleft()
        scanned += 1
        if on_progress is not None and scanned % 200 == 0:
            on_progress(scanned, current)
        try:
            with os.scandir(os_path(current)) as it:
                for entry in it:
                    try:
                        link = is_link_entry(entry)
                        is_dir = entry.is_dir(follow_symlinks=False) and not link
                    except OSError:
                        continue
                    if is_dir:
                        queue.append(os.path.join(current, entry.name))
                    if match(entry.name):
                        try:
                            size = 0 if is_dir else entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            size = 0
                        hit = SearchHit(entry.name, os.path.join(current, entry.name), is_dir, size)
                        hits.append(hit)
                        batch.append(hit)
                        if on_batch is not None and len(batch) >= batch_size:
                            on_batch(batch)
                            batch = []
                        if len(hits) >= max_results:
                            queue.clear()
                            break
        except OSError:
            continue
    if on_batch is not None and batch:
        on_batch(batch)
    return hits
