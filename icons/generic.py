"""Generic, procedurally drawn icons (fallback when no system icon is available)."""
from __future__ import annotations

from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from filesystem.filetypes import CATEGORY_COLORS

ICON_SIZE = 64


def _rgb(c, k=1.0):
    return tuple(int(max(0, min(1, v * k)) * 255) for v in c)


@lru_cache(maxsize=8)
def _font(size: int):
    for name in ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def folder_icon(size: int = ICON_SIZE) -> Image.Image:
    s = size / 64.0
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    back = (222, 168, 40, 255)
    front = (252, 206, 84, 255)
    d.rounded_rectangle([4 * s, 10 * s, 28 * s, 22 * s], radius=3 * s, fill=back)
    d.rounded_rectangle([4 * s, 15 * s, 60 * s, 54 * s], radius=4 * s, fill=back)
    d.rounded_rectangle([4 * s, 21 * s, 60 * s, 56 * s], radius=4 * s, fill=front)
    d.line([6 * s, 23 * s, 58 * s, 23 * s], fill=(255, 232, 150, 255), width=max(1, int(2 * s)))
    return img


def file_icon(category: str, ext: str = "", size: int = ICON_SIZE) -> Image.Image:
    s = size / 64.0
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    col = CATEGORY_COLORS.get(category, CATEGORY_COLORS["other"])
    fold = 14 * s
    x0, y0, x1, y1 = 12 * s, 4 * s, 52 * s, 60 * s
    page = [(x0, y0), (x1 - fold, y0), (x1, y0 + fold), (x1, y1), (x0, y1)]
    d.polygon(page, fill=(246, 248, 252, 255), outline=(150, 160, 175, 255))
    d.polygon([(x1 - fold, y0), (x1 - fold, y0 + fold), (x1, y0 + fold)], fill=(205, 212, 225, 255))
    d.rectangle([x0, 36 * s, x1, 52 * s], fill=_rgb(col, 0.85) + (255,))
    # category glyph
    cx, cy = 32 * s, 22 * s
    g = _rgb(col, 0.7) + (255,)
    if category == "image":
        d.polygon([(20 * s, 31 * s), (29 * s, 18 * s), (36 * s, 27 * s), (40 * s, 22 * s), (46 * s, 31 * s)], fill=g)
        d.ellipse([22 * s, 12 * s, 28 * s, 18 * s], fill=g)
    elif category == "video":
        d.polygon([(26 * s, 13 * s), (26 * s, 31 * s), (41 * s, 22 * s)], fill=g)
    elif category == "audio":
        d.ellipse([22 * s, 25 * s, 30 * s, 32 * s], fill=g)
        d.rectangle([28 * s, 12 * s, 30 * s, 29 * s], fill=g)
        d.polygon([(30 * s, 12 * s), (40 * s, 16 * s), (30 * s, 19 * s)], fill=g)
    elif category == "archive":
        for k in range(5):
            d.rectangle([30 * s, (11 + 4 * k) * s, 34 * s, (13 + 4 * k) * s], fill=g)
    elif category == "code":
        d.line([(24 * s, 22 * s), (19 * s, cy), (24 * s, 27 * s)], fill=g, width=int(3 * s))
        d.line([(24 * s, 17 * s), (19 * s, cy)], fill=g, width=int(3 * s))
        d.line([(40 * s, 17 * s), (45 * s, cy), (40 * s, 27 * s)], fill=g, width=int(3 * s))
    elif category == "executable":
        d.rectangle([19 * s, 12 * s, 45 * s, 31 * s], outline=g, width=int(3 * s))
        d.rectangle([19 * s, 12 * s, 45 * s, 16 * s], fill=g)
    else:
        for k in range(4):
            d.line([(19 * s, (13 + 5 * k) * s), ((45 - 6 * (k % 2)) * s, (13 + 5 * k) * s)], fill=g, width=int(2 * s))
    if ext:
        label = ext[:4].upper()
        f = _font(max(8, int(11 * s)))
        bbox = d.textbbox((0, 0), label, font=f)
        tw = bbox[2] - bbox[0]
        d.text((32 * s - tw / 2, 37 * s), label, fill=(255, 255, 255, 255), font=f)
    return img


def drive_icon(kind: str, size: int = ICON_SIZE) -> Image.Image:
    s = size / 64.0
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if kind == "disc":
        d.ellipse([6 * s, 6 * s, 58 * s, 58 * s], fill=(210, 215, 230, 255), outline=(140, 150, 170, 255))
        d.ellipse([12 * s, 12 * s, 52 * s, 52 * s], outline=(240, 200, 255, 255), width=int(3 * s))
        d.ellipse([27 * s, 27 * s, 37 * s, 37 * s], fill=(0, 0, 0, 0), outline=(120, 120, 140, 255))
    elif kind == "usb":
        d.rounded_rectangle([6 * s, 22 * s, 44 * s, 42 * s], radius=5 * s, fill=(60, 180, 110, 255))
        d.rectangle([44 * s, 25 * s, 60 * s, 39 * s], fill=(200, 205, 210, 255))
        d.rectangle([49 * s, 28 * s, 53 * s, 31 * s], fill=(60, 60, 60, 255))
    elif kind == "sd":
        d.polygon([(16 * s, 4 * s), (50 * s, 4 * s), (50 * s, 60 * s), (12 * s, 60 * s), (12 * s, 10 * s)], fill=(40, 60, 110, 255))
        for k in range(6):
            d.rectangle([(18 + 5 * k) * s, 7 * s, (21 + 5 * k) * s, 15 * s], fill=(230, 190, 70, 255))
    elif kind == "hdd":
        d.rounded_rectangle([8 * s, 6 * s, 56 * s, 58 * s], radius=5 * s, fill=(140, 145, 155, 255))
        d.ellipse([14 * s, 10 * s, 50 * s, 46 * s], fill=(210, 215, 225, 255))
        d.ellipse([29 * s, 25 * s, 35 * s, 31 * s], fill=(90, 90, 100, 255))
        d.line([(46 * s, 50 * s), (33 * s, 30 * s)], fill=(60, 60, 70, 255), width=int(3 * s))
    elif kind == "network":
        d.ellipse([10 * s, 18 * s, 54 * s, 50 * s], fill=(90, 170, 230, 255))
        d.line([(32 * s, 50 * s), (32 * s, 60 * s)], fill=(200, 200, 210, 255), width=int(3 * s))
    else:
        d.rounded_rectangle([6 * s, 18 * s, 58 * s, 46 * s], radius=4 * s, fill=(70, 120, 200, 255))
        for k in range(4):
            d.rectangle([(12 + 11 * k) * s, 24 * s, (19 + 11 * k) * s, 34 * s], fill=(20, 25, 35, 255))
        d.rectangle([10 * s, 40 * s, 54 * s, 43 * s], fill=(230, 190, 70, 255))
    return img


def generic_for_key(key: str) -> Image.Image:
    """Keys: 'gen:folder', 'gen:<category>:<ext>', 'gen:drive:<kind>'."""
    parts = key.split(":")
    if len(parts) >= 2 and parts[1] == "folder":
        return folder_icon()
    if len(parts) >= 3 and parts[1] == "drive":
        return drive_icon(parts[2])
    cat = parts[1] if len(parts) > 1 else "other"
    ext = parts[2] if len(parts) > 2 else ""
    return file_icon(cat, ext)
