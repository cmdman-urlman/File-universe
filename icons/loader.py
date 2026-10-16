"""Asynchronous icon loading with caching.

Requests are keyed by the scene's icon key ("file:<path>", "dir:<path>",
"drive:<mount>"). Each request is resolved to a *canonical* key so identical
icons share one cache entry and one atlas slot:

* executables, shortcuts, .ico files, folders with desktop.ini, drives -> per path
* images -> a real thumbnail of the picture ("thumb:<path>")
* everything else -> per extension ("ext:.txt"), looked up without touching the file
"""
from __future__ import annotations

import os
import threading
from collections import OrderedDict, deque

from PIL import Image
from PyQt6.QtCore import QObject, pyqtSignal

from filesystem.filetypes import PREVIEWABLE_IMAGES, category_for, extension
from filesystem.paths import os_path
from filesystem.threads import safe_emit

from . import windows_icons
from .generic import ICON_SIZE, generic_for_key

PER_PATH_EXTS = {"exe", "ico", "lnk", "cur", "url", "scr", "msc", "appref-ms", "cpl"}
MAX_IMAGE_THUMB_BYTES = 60 * 1024 * 1024


def generic_key(request_key: str) -> str:
    kind, _, path = request_key.partition(":")
    if kind == "dir":
        return "gen:folder"
    if kind == "drive":
        return "gen:drive:ssd"
    name = os.path.basename(path)
    return f"gen:{category_for(name)}:{extension(name)}"


def _square(img: Image.Image, size: int = ICON_SIZE) -> Image.Image:
    img = img.convert("RGBA")
    img.thumbnail((size, size), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(img, ((size - img.width) // 2, (size - img.height) // 2), img)
    return canvas


class IconService(QObject):
    icon_ready = pyqtSignal(str)          # request key

    def __init__(self, workers: int = 2, max_cached: int = 3000, parent=None):
        super().__init__(parent)
        self._images: "OrderedDict[str, Image.Image]" = OrderedDict()
        self._resolved: dict[str, str] = {}          # request key -> canonical key
        self._type_names: dict[str, str] = {}
        self._lock = threading.Lock()
        self._queue: deque[tuple[str, str, bool]] = deque()
        self._pending: set[str] = set()
        self._cv = threading.Condition(self._lock)
        self._stop = False
        self.max_cached = max_cached
        self.drive_kinds: dict[str, str] = {}
        self._threads = [threading.Thread(target=self._worker, daemon=True, name=f"icons-{i}") for i in range(workers)]
        for t in self._threads:
            t.start()

    # ---- public API (GUI thread) -------------------------------------------
    def canonical(self, request_key: str) -> str | None:
        return self._resolved.get(request_key)

    def image(self, canonical_key: str) -> Image.Image | None:
        if canonical_key.startswith("gen:"):
            with self._lock:
                img = self._images.get(canonical_key)
            if img is None:
                img = generic_for_key(canonical_key)
                self._store(canonical_key, img)
            return img
        with self._lock:
            img = self._images.get(canonical_key)
            if img is not None:
                self._images.move_to_end(canonical_key)
            return img

    def type_name(self, request_key: str) -> str | None:
        return self._type_names.get(request_key)

    def request(self, request_key: str, priority: bool = True) -> None:
        if request_key in self._resolved:
            canon = self._resolved[request_key]
            if canon.startswith("gen:") or canon in self._images:
                return
        with self._cv:
            if request_key in self._pending:
                return
            self._pending.add(request_key)
            kind, _, path = request_key.partition(":")
            item = (request_key, path, kind == "dir")
            if priority:
                self._queue.appendleft(item)
            else:
                self._queue.append(item)
            while len(self._queue) > 600:          # drop stale requests
                old = self._queue.pop()
                self._pending.discard(old[0])
            self._cv.notify()

    def clear_queue(self) -> None:
        with self._cv:
            self._queue.clear()
            self._pending.clear()

    def shutdown(self) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify_all()

    # ---- worker ------------------------------------------------------------
    def _store(self, key: str, img: Image.Image) -> None:
        with self._lock:
            self._images[key] = img
            self._images.move_to_end(key)
            while len(self._images) > self.max_cached:
                self._images.popitem(last=False)

    def _worker(self) -> None:
        windows_icons.com_init()
        while True:
            with self._cv:
                while not self._queue and not self._stop:
                    self._cv.wait()
                if self._stop:
                    return
                request_key, path, is_dir = self._queue.popleft()
            try:
                canon = self._load(request_key, path, is_dir)
            except Exception:
                canon = generic_key(request_key)
            self._resolved[request_key] = canon
            with self._cv:
                self._pending.discard(request_key)
            safe_emit(self.icon_ready, request_key)

    def _load(self, request_key: str, path: str, is_dir: bool) -> str:
        kind = request_key.partition(":")[0]
        if kind == "drive":
            canon = "drive:" + path
            res = windows_icons.system_icon(path, True, ICON_SIZE)
            if res is None:
                return "gen:drive:" + self.drive_kinds.get(path, "ssd")
            self._store(canon, res[0])
            self._type_names[request_key] = res[1]
            return canon
        if is_dir:
            custom = os.path.exists(os_path(os.path.join(path, "desktop.ini")))
            canon = ("diricon:" + path) if custom else "sys:folder"
            if canon in self._images:
                return canon
            res = windows_icons.system_icon(path if custom else "folder", True, ICON_SIZE, by_attributes=not custom)
            if res is None:
                return "gen:folder"
            self._store(canon, res[0])
            return canon
        ext = extension(path)
        if ext in PREVIEWABLE_IMAGES:
            canon = "thumb:" + path
            try:
                from previews.images import load_thumbnail
                if os.path.getsize(os_path(path)) <= MAX_IMAGE_THUMB_BYTES:
                    thumb, _ = load_thumbnail(path, ICON_SIZE)
                    if thumb is not None:
                        self._store(canon, _square(thumb))
                        return canon
            except Exception:
                pass
        if ext in PER_PATH_EXTS:
            canon = "path:" + path
            res = windows_icons.system_icon(path, False, ICON_SIZE)
        else:
            canon = "ext:." + ext
            if canon in self._images:
                return canon
            res = windows_icons.system_icon("file." + ext if ext else "file", False, ICON_SIZE, by_attributes=True)
        if res is None:
            return generic_key(request_key)
        self._store(canon, res[0])
        self._type_names[request_key] = res[1]
        return canon
