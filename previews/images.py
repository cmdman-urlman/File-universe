"""Safe image thumbnail loading (decoded as data only, with size guards)."""
from __future__ import annotations

import os
import warnings

from PIL import Image

from filesystem.paths import os_path

Image.MAX_IMAGE_PIXELS = 120_000_000          # refuse decompression bombs
MAX_FILE_BYTES = 200 * 1024 * 1024


def image_dimensions(path: str) -> tuple[int, int] | None:
    try:
        with Image.open(os_path(path)) as im:
            return im.size
    except Exception:
        return None


def load_thumbnail(path: str, max_size: int = 256) -> tuple[Image.Image | None, tuple[int, int] | None]:
    """Return (RGBA thumbnail, original (w, h)) or (None, None)."""
    try:
        if os.path.getsize(os_path(path)) > MAX_FILE_BYTES:
            return None, image_dimensions(path)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(os_path(path)) as im:
                dims = im.size
                if im.format == "JPEG":
                    im.draft("RGB", (max_size * 2, max_size * 2))   # fast DCT downscale
                try:
                    im.seek(0)
                except Exception:
                    pass
                im = im.convert("RGBA")
                im.thumbnail((max_size, max_size), Image.LANCZOS)
                return im.copy(), dims
    except Exception:
        return None, None


def planet_texture(img: Image.Image, size: tuple[int, int] = (512, 256)) -> Image.Image:
    """Wrap an image into an equirectangular planet texture (mirrored seam)."""
    w, h = size
    rgba = img.convert("RGBA")
    # composite on black: transparent pixels may carry arbitrary hidden colours
    src = Image.alpha_composite(Image.new("RGBA", rgba.size, (0, 0, 0, 255)), rgba).convert("RGB")
    half = src.resize((w // 2, h), Image.LANCZOS)
    out = Image.new("RGB", (w, h))
    out.paste(half, (0, 0))
    out.paste(half.transpose(Image.FLIP_LEFT_RIGHT), (w // 2, 0))
    return out.convert("RGBA")
