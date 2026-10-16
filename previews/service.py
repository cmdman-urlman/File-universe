"""Background preview generation for the properties panel and textured planets."""
from __future__ import annotations

import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from PIL import Image
from PyQt6.QtCore import QObject, pyqtSignal

from filesystem.filetypes import PREVIEWABLE_IMAGES, category_for, extension
from filesystem.threads import safe_emit


@dataclass
class Preview:
    path: str
    image: Image.Image | None = None
    info: dict = field(default_factory=dict)
    kind: str = "none"            # image | video | audio | none


def build_preview(path: str, size: int = 320) -> Preview:
    ext = extension(path)
    cat = category_for(path)
    pv = Preview(path)
    if ext in PREVIEWABLE_IMAGES or cat == "image":
        from .images import load_thumbnail
        img, dims = load_thumbnail(path, size)
        pv.image, pv.kind = img, "image"
        if dims:
            pv.info["Dimensions"] = f"{dims[0]} × {dims[1]} px"
    elif cat == "video":
        from .video import extract_frame, probe
        pv.kind = "video"
        info = probe(path)
        pv.image = extract_frame(path, size, at_seconds=min(5.0, (info.get("duration") or 2.0) * 0.1))
        if info.get("width"):
            pv.info["Dimensions"] = f"{info['width']} × {info['height']} px"
        if info.get("duration"):
            pv.info["Duration"] = _fmt_duration(info["duration"])
        if info.get("video_codec"):
            pv.info["Codec"] = info["video_codec"]
    elif cat == "audio":
        from .audio import waveform_image
        from .video import probe
        pv.kind = "audio"
        pv.image, duration = waveform_image(path, (size, 110))
        info = probe(path)
        dur = info.get("duration") or duration
        if dur:
            pv.info["Duration"] = _fmt_duration(dur)
        if info.get("audio_codec"):
            pv.info["Codec"] = f"{info['audio_codec']} {info.get('sample_rate') or ''} Hz".strip()
    return pv


def _fmt_duration(sec: float) -> str:
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class PreviewService(QObject):
    preview_ready = pyqtSignal(str)          # path
    texture_ready = pyqtSignal(str)          # path (planet texture available)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="preview",
                                        initializer=_com_init)
        self._cache: "OrderedDict[str, Preview]" = OrderedDict()
        self._textures: "OrderedDict[str, Image.Image]" = OrderedDict()
        self._pending: set[str] = set()
        self._tex_pending: set[str] = set()
        self._lock = threading.Lock()

    def get(self, path: str) -> Preview | None:
        with self._lock:
            return self._cache.get(path)

    def request(self, path: str) -> None:
        with self._lock:
            if path in self._cache or path in self._pending:
                return
            self._pending.add(path)
        self._pool.submit(self._run, path)

    def _run(self, path: str) -> None:
        try:
            pv = build_preview(path)
        except Exception:
            pv = Preview(path)
        with self._lock:
            self._pending.discard(path)
            self._cache[path] = pv
            while len(self._cache) > 64:
                self._cache.popitem(last=False)
        safe_emit(self.preview_ready, path)

    # planet textures for image files
    def texture(self, path: str) -> Image.Image | None:
        with self._lock:
            return self._textures.get(path)

    def request_texture(self, path: str) -> None:
        with self._lock:
            if path in self._textures or path in self._tex_pending or len(self._tex_pending) > 8:
                return
            self._tex_pending.add(path)
        self._pool.submit(self._run_texture, path)

    def _run_texture(self, path: str) -> None:
        from .images import load_thumbnail, planet_texture
        img, _ = load_thumbnail(path, 384)
        with self._lock:
            self._tex_pending.discard(path)
            if img is None:
                return
            self._textures[path] = planet_texture(img)
            while len(self._textures) > 48:
                self._textures.popitem(last=False)
        safe_emit(self.texture_ready, path)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


def _com_init() -> None:
    try:
        from icons.windows_icons import com_init
        com_init()
    except Exception:
        pass
