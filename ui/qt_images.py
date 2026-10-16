"""PIL <-> Qt image helpers and a small icon pixmap cache."""
from __future__ import annotations

from collections import OrderedDict

from PIL import Image
from PyQt6.QtGui import QIcon, QImage, QPixmap

from icons.loader import generic_key


def pil_to_qimage(img: Image.Image) -> QImage:
    img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    return QImage(data, img.width, img.height, img.width * 4, QImage.Format.Format_RGBA8888).copy()


def pil_to_pixmap(img: Image.Image) -> QPixmap:
    return QPixmap.fromImage(pil_to_qimage(img))


class IconPixmaps:
    """QIcons for list views, sourced from the shared IconService."""

    def __init__(self, icon_service, capacity: int = 800):
        self.service = icon_service
        self._cache: "OrderedDict[str, QIcon]" = OrderedDict()
        self.capacity = capacity

    def icon(self, request_key: str, request: bool = True) -> QIcon:
        canon = request_key if request_key.startswith("gen:") else self.service.canonical(request_key)
        if canon is None:
            if request:
                self.service.request(request_key, priority=False)
            canon = generic_key(request_key)
        ic = self._cache.get(canon)
        if ic is not None:
            self._cache.move_to_end(canon)
            return ic
        img = self.service.image(canon)
        if img is None:
            img = self.service.image(generic_key(request_key))
        ic = QIcon(pil_to_pixmap(img.resize((32, 32), Image.LANCZOS))) if img is not None else QIcon()
        self._cache[canon] = ic
        while len(self._cache) > self.capacity:
            self._cache.popitem(last=False)
        return ic
