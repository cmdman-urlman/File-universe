"""Qt-facing background filesystem service.

Worker threads only *read* the disk and send plain data back through queued
signals; the :class:`FileSystemModel` is mutated exclusively on the GUI
thread, so no locking of the model is needed.
"""
from __future__ import annotations

import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from universe.mapping import format_size

from .models import FileSystemModel, FSNode, ScanState
from .paths import norm_key
from .scanner import list_directory, sample_directory, stat_path
from .search import search_tree
from .sizes import SizeCache, SizeResult, compute_tree_size
from .threads import safe_emit

MAX_PREVIEW_DIRS = 300


class ScanService(QObject):
    listing_ready = pyqtSignal(str)                 # dir key
    previews_ready = pyqtSignal(str)                # dir key
    sizes_updated = pyqtSignal(list)                # list of dir keys whose sizes changed
    progress = pyqtSignal(str, int, int)            # text, done, total (total 0 = idle/indeterminate)
    search_batch = pyqtSignal(int, list)            # token, hits
    search_done = pyqtSignal(int, int, bool)        # token, count, cancelled

    _listing_done = pyqtSignal(str, object, object)          # path, entries, error
    _previews_done = pyqtSignal(str, object)                  # parent path, [(path, sample, total)]
    _size_done = pyqtSignal(int, str, object, bool)           # generation, path, SizeResult, final

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = FileSystemModel()
        self.size_cache = SizeCache()
        self._pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="scan")
        self._listing_pending: set[str] = set()
        self._listing_cancel = threading.Event()
        self._size_queue: "queue.Queue[tuple[int, str, float | None]]" = queue.Queue()
        self._size_generation = 0
        self._size_cancel = threading.Event()
        self._size_total = 0
        self._size_done_count = 0
        self._size_current = ""
        self._changed: set[str] = set()
        self._protected: set[str] = set()
        self._search_cancel: threading.Event | None = None
        self._search_token = 0
        self._stop = False
        self._listing_done.connect(self._on_listing)
        self._previews_done.connect(self._on_previews)
        self._size_done.connect(self._on_size)
        self._flush = QTimer(self)
        self._flush.setInterval(350)
        self._flush.timeout.connect(self._flush_sizes)
        self._flush.start()
        self._size_thread = threading.Thread(target=self._size_worker, daemon=True, name="sizes")
        self._size_thread.start()

    # ---- listings ---------------------------------------------------------------
    def set_protected(self, paths: list[str]) -> None:
        """Ancestors of the current location are never evicted from the LRU."""
        self._protected = {norm_key(p) for p in paths}

    def request_listing(self, path: str, force: bool = False) -> FSNode:
        node = self.model.get_or_create_dir(path)
        k = node.key
        if not force and node.children is not None:
            QTimer.singleShot(0, lambda: self.listing_ready.emit(k))
            return node
        if k in self._listing_pending:
            return node
        self._listing_pending.add(k)
        node.list_state = ScanState.SCANNING
        self.progress.emit(f"Scanning {path}", 0, 0)
        self._pool.submit(self._list_job, path)
        return node

    def _list_job(self, path: str) -> None:
        entries, error = list_directory(path)
        safe_emit(self._listing_done, path, entries, error)

    def _on_listing(self, path: str, entries, error) -> None:
        k = norm_key(path)
        self._listing_pending.discard(k)
        node = self.model.apply_listing(path, entries, error, self._protected)
        if node.mtime is None:                     # e.g. drive roots, opened directly
            info = stat_path(path)
            if info is not None:
                node.mtime = info.mtime
        for c in node.children or []:
            if c.is_dir:
                self._apply_cached_size(c)
        self._update_aggregate(node)
        self.progress.emit("", 0, 0)
        self.listing_ready.emit(k)
        dirs = [c.path for c in (node.children or []) if c.is_dir and c.preview is None][:MAX_PREVIEW_DIRS]
        if dirs:
            self._pool.submit(self._preview_job, path, dirs)

    def _preview_job(self, parent: str, dirs: list[str]) -> None:
        out = []
        t0 = time.monotonic()
        for d in dirs:
            if self._stop:
                return
            sample, total = sample_directory(d)
            out.append((d, sample, total))
            if len(out) >= 40 or time.monotonic() - t0 > 0.5:
                safe_emit(self._previews_done, parent, out)
                out, t0 = [], time.monotonic()
        if out:
            safe_emit(self._previews_done, parent, out)

    def _on_previews(self, parent: str, results) -> None:
        for path, sample, total in results:
            n = self.model.get(path)
            if n is not None:
                n.preview, n.preview_total = sample, total
        self.previews_ready.emit(norm_key(parent))

    # ---- sizes ------------------------------------------------------------------
    def _apply_cached_size(self, node: FSNode) -> bool:
        res = self.size_cache.get(node.path, node.mtime)
        if res is None:
            return False
        self._apply_size(node, res, True)
        return True

    def _apply_size(self, node: FSNode, res: SizeResult, final: bool) -> None:
        if not final and node.total_size is not None and res.total < node.total_size:
            return      # a restarted walk must not shrink an earlier, larger estimate
        node.total_size = res.total
        node.file_count = res.files
        node.dir_count = res.dirs
        node.size_errors = res.errors
        node.size_complete = final and res.complete

    def request_sizes(self, dir_node: FSNode) -> None:
        """Measure every sub-folder of *dir_node* (cancels earlier measurements)."""
        self.cancel_sizes()
        self._size_generation += 1
        gen = self._size_generation
        self._size_cancel = threading.Event()
        jobs = [c for c in (dir_node.children or []) if c.is_dir and not c.is_link and not c.size_complete]
        # small folders first so most objects get their true size quickly
        jobs.sort(key=lambda c: (c.preview_total or 0))
        self._size_total = len(jobs)
        self._size_done_count = 0
        for c in jobs:
            if not self._apply_cached_size(c):
                self._size_queue.put((gen, c.path, c.mtime))
            else:
                self._size_done_count += 1
        self._changed.add(dir_node.key)
        self._update_aggregate(dir_node)
        if self._size_done_count < self._size_total:
            self.progress.emit("Measuring folder sizes…", self._size_done_count, self._size_total)

    def cancel_sizes(self) -> None:
        self._size_cancel.set()
        self._size_generation += 1
        try:
            while True:
                self._size_queue.get_nowait()
        except queue.Empty:
            pass

    def _size_worker(self) -> None:
        while not self._stop:
            try:
                gen, path, mtime = self._size_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if gen != self._size_generation:
                continue
            cancel = self._size_cancel
            self._size_current = path

            def progress(partial: SizeResult, current: str, _g=gen, _p=path):
                safe_emit(self._size_done, _g, _p, partial, False)

            res = compute_tree_size(path, cancel, self.size_cache, progress, root_mtime=mtime)
            safe_emit(self._size_done, gen, path, res, not cancel.is_set())

    def _on_size(self, gen: int, path: str, res: SizeResult, final: bool) -> None:
        if gen != self._size_generation:
            return
        node = self.model.get(path)
        if node is None:
            return
        self._apply_size(node, res, final)
        if final:
            self._size_done_count += 1
        parent = node.parent
        if parent is not None:
            self._update_aggregate(parent)
            self._changed.add(parent.key)
        self._changed.add(node.key)
        if self._size_done_count >= self._size_total:
            self.progress.emit("Folder sizes complete", 0, 0)
        else:
            self.progress.emit(f"Measuring folder sizes — {self._size_done_count}/{self._size_total}: "
                               f"{node.name} ({format_size(res.total)} so far)",
                               self._size_done_count, self._size_total)

    def _update_aggregate(self, node: FSNode) -> None:
        """A listed folder's total is the sum of its children (estimate until all are measured)."""
        if node.children is None:
            return
        total, files, dirs, complete, errors = 0, 0, 0, True, 0
        for c in node.children:
            if c.is_dir:
                dirs += 1
                if c.is_link:
                    continue
                if c.total_size is not None:
                    total += c.total_size
                    files += c.file_count or 0
                    dirs += c.dir_count or 0
                    errors += c.size_errors
                if not c.size_complete:
                    complete = False
            else:
                total += c.size
                files += 1
        node.total_size, node.file_count, node.dir_count = total, files, dirs
        node.size_errors = errors
        node.size_complete = complete and node.list_state == ScanState.COMPLETE and not node.error
        if node.size_complete:
            self.size_cache.put(node.path, SizeResult(total, files, dirs, errors, True), node.mtime)

    def _flush_sizes(self) -> None:
        if self._changed:
            changed = list(self._changed)
            self._changed.clear()
            self.sizes_updated.emit(changed)

    # ---- search -----------------------------------------------------------------
    def search(self, roots: list[str] | str, query: str) -> int:
        if isinstance(roots, str):
            roots = [roots]
        self.cancel_search()
        self._search_token += 1
        token = self._search_token
        cancel = threading.Event()
        self._search_cancel = cancel

        def run():
            count = 0
            for root in roots:
                if cancel.is_set():
                    break
                hits = search_tree(root, query, cancel, on_batch=lambda b: safe_emit(self.search_batch, token, list(b)),
                                   max_results=max(1, 5000 - count),
                                   on_progress=lambda n, cur: safe_emit(self.progress, f"Searching… {n:,} folders: {cur}", 0, 0))
                count += len(hits)
            safe_emit(self.search_done, token, count, cancel.is_set())
            safe_emit(self.progress, "", 0, 0)

        threading.Thread(target=run, daemon=True, name="search").start()
        return token

    def cancel_search(self) -> None:
        if self._search_cancel is not None:
            self._search_cancel.set()

    # ---- misc ---------------------------------------------------------------------
    def invalidate(self, path: str | None = None) -> None:
        self.model.invalidate(path)
        self.size_cache.clear()

    def cancel_all(self) -> None:
        self.cancel_sizes()
        self.cancel_search()
        self.progress.emit("Cancelled", 0, 0)

    def shutdown(self) -> None:
        self._stop = True
        self.cancel_all()
        self._pool.shutdown(wait=False, cancel_futures=True)
