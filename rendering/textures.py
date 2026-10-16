"""GPU texture caches: the icon atlas and per-image planet textures."""
from __future__ import annotations

from collections import OrderedDict

import numpy as np
from OpenGL import GL as gl

from filesystem.filetypes import CATEGORY_COLORS
from icons.generic import ICON_SIZE
from icons.loader import generic_key
from icons.texture_cache import AtlasAllocator

from .gl_utils import create_texture_rgba

ATLAS_SIZE = 2048
UPLOADS_PER_FRAME = 32


class IconAtlas:
    def __init__(self, icon_service):
        self.service = icon_service
        self.alloc = AtlasAllocator(ATLAS_SIZE, ICON_SIZE)
        self.tex = create_texture_rgba(ATLAS_SIZE, ATLAS_SIZE, None, mipmap=False)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR_MIPMAP_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAX_LEVEL, 4)
        self._budget = UPLOADS_PER_FRAME
        self._dirty = False
        pinned = ["gen:folder"] + [f"gen:{c}:" for c in CATEGORY_COLORS] + \
                 [f"gen:drive:{k}" for k in ("ssd", "hdd", "usb", "disc", "sd", "network", "ram", "unknown")]
        for key in pinned:
            self._upload(key, pinned=True)
        self.end_frame()

    def _upload(self, canon: str, pinned: bool = False) -> int | None:
        img = self.service.image(canon)
        if img is None:
            return None
        if img.size != (ICON_SIZE, ICON_SIZE):
            img = img.resize((ICON_SIZE, ICON_SIZE))
        slot, _ = self.alloc.allocate(canon, pinned)
        x, y = self.alloc.cell_origin(slot)
        data = np.ascontiguousarray(np.asarray(img.convert("RGBA"), np.uint8))
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.tex)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
        gl.glTexSubImage2D(gl.GL_TEXTURE_2D, 0, x, y, ICON_SIZE, ICON_SIZE, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, data)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 4)     # Qt's glyph uploads expect the default
        self._dirty = True
        return slot

    def begin_frame(self) -> None:
        self._budget = UPLOADS_PER_FRAME

    def end_frame(self) -> None:
        if self._dirty:
            gl.glBindTexture(gl.GL_TEXTURE_2D, self.tex)
            gl.glGenerateMipmap(gl.GL_TEXTURE_2D)
            self._dirty = False

    def uv_for(self, request_key: str) -> tuple[float, float, float, float]:
        canon = self.service.canonical(request_key)
        if canon is None:
            self.service.request(request_key)
            canon = generic_key(request_key)
        slot = self.alloc.get(canon)
        if slot is None and self._budget > 0:
            self._budget -= 1
            slot = self._upload(canon)
        if slot is None:
            g = generic_key(request_key)
            fallback = g.rsplit(":", 1)[0] + ":" if not g.startswith(("gen:folder", "gen:drive")) else g
            slot = self.alloc.get(fallback)
            if slot is None:
                slot = self.alloc.get("gen:other:")
        return self.alloc.uv_rect(slot)


class ImageTextures:
    """Small LRU of GL textures made from image previews (textured planets)."""

    def __init__(self, preview_service, capacity: int = 40):
        self.service = preview_service
        self.capacity = capacity
        self._tex: "OrderedDict[str, int]" = OrderedDict()

    def get(self, path: str) -> int | None:
        tex = self._tex.get(path)
        if tex is not None:
            self._tex.move_to_end(path)
            return tex
        img = self.service.texture(path)
        if img is None:
            self.service.request_texture(path)
            return None
        data = np.ascontiguousarray(np.asarray(img.convert("RGBA"), np.uint8))
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
        tex = create_texture_rgba(img.width, img.height, data, mipmap=True)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 4)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_REPEAT)
        self._tex[path] = tex
        while len(self._tex) > self.capacity:
            _, old = self._tex.popitem(last=False)
            gl.glDeleteTextures(1, [old])
        return tex
