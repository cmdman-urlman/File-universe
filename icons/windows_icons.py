"""Native Windows shell icons and thumbnails via ctypes (no extra packages).

* :func:`system_icon` uses ``SHGetFileInfo`` + the shell's jumbo/extra-large
  image lists, so executables show their embedded icons and folders show
  custom ``desktop.ini`` icons, exactly like Explorer.
* :func:`shell_thumbnail` uses ``IShellItemImageFactory`` (the Explorer
  thumbnail cache) and is used as a fallback for video thumbnails.

Neither function executes the file. Callers must initialise COM on the
calling thread (:func:`com_init`). Every function returns ``None`` on failure.
"""
from __future__ import annotations

import ctypes
import sys
import uuid
from ctypes import wintypes

from PIL import Image

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    shell32 = ctypes.windll.shell32
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    ole32 = ctypes.windll.ole32
    HRESULT = ctypes.c_long

    class GUID(ctypes.Structure):
        _fields_ = [("data", ctypes.c_ubyte * 16)]

        @classmethod
        def from_str(cls, s: str) -> "GUID":
            g = cls()
            ctypes.memmove(g.data, uuid.UUID(s).bytes_le, 16)
            return g

    class SHFILEINFOW(ctypes.Structure):
        _fields_ = [("hIcon", wintypes.HICON), ("iIcon", ctypes.c_int), ("dwAttributes", wintypes.DWORD),
                    ("szDisplayName", wintypes.WCHAR * 260), ("szTypeName", wintypes.WCHAR * 80)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

    class BITMAP(ctypes.Structure):
        _fields_ = [("bmType", ctypes.c_long), ("bmWidth", ctypes.c_long), ("bmHeight", ctypes.c_long),
                    ("bmWidthBytes", ctypes.c_long), ("bmPlanes", wintypes.WORD), ("bmBitsPixel", wintypes.WORD),
                    ("bmBits", ctypes.c_void_p)]

    class SIZE(ctypes.Structure):
        _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

    shell32.SHGetFileInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(SHFILEINFOW), wintypes.UINT, wintypes.UINT]
    shell32.SHGetFileInfoW.restype = ctypes.c_void_p
    shell32.SHGetImageList.argtypes = [ctypes.c_int, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
    shell32.SHGetImageList.restype = HRESULT
    shell32.SHCreateItemFromParsingName.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
    shell32.SHCreateItemFromParsingName.restype = HRESULT
    user32.DrawIconEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.HICON, ctypes.c_int, ctypes.c_int,
                                  wintypes.UINT, wintypes.HBRUSH, wintypes.UINT]
    user32.DestroyIcon.argtypes = [wintypes.HICON]
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p]
    gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]

    IID_IImageList = GUID.from_str("46EB5926-582E-4017-9FDF-E8998DAA0950")
    IID_IShellItemImageFactory = GUID.from_str("BCC18B79-BA16-442F-80C4-8A59C30C463B")

SHGFI_SYSICONINDEX = 0x4000
SHGFI_TYPENAME = 0x400
SHGFI_USEFILEATTRIBUTES = 0x10
FILE_ATTRIBUTE_DIRECTORY = 0x10
FILE_ATTRIBUTE_NORMAL = 0x80
SHIL_EXTRALARGE, SHIL_JUMBO = 2, 4
ILD_TRANSPARENT = 0x1
DI_NORMAL = 0x3
SIIGBF_RESIZETOFIT, SIIGBF_BIGGERSIZEOK, SIIGBF_ICONONLY, SIIGBF_THUMBNAILONLY = 0x0, 0x1, 0x4, 0x8


def com_init() -> None:
    if IS_WINDOWS:
        try:
            ole32.CoInitializeEx(None, 0x2)   # COINIT_APARTMENTTHREADED
        except Exception:
            pass


def _vtable_fn(obj: ctypes.c_void_p, index: int, restype, *argtypes):
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return proto(vtbl[index])


def _release(obj: ctypes.c_void_p) -> None:
    if obj:
        _vtable_fn(obj, 2, ctypes.c_ulong)(obj)


def _render_icon(hicon, size: int, background: int) -> bytes | None:
    hdc = gdi32.CreateCompatibleDC(None)
    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth, bmi.biHeight = size, -size
    bmi.biPlanes, bmi.biBitCount = 1, 32
    bits = ctypes.c_void_p()
    hbmp = gdi32.CreateDIBSection(hdc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    if not hbmp:
        gdi32.DeleteDC(hdc)
        return None
    old = gdi32.SelectObject(hdc, hbmp)
    ctypes.memset(bits, background, size * size * 4)
    user32.DrawIconEx(hdc, 0, 0, hicon, size, size, 0, None, DI_NORMAL)
    data = ctypes.string_at(bits, size * size * 4)
    gdi32.SelectObject(hdc, old)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc)
    return data


def hicon_to_image(hicon, size: int) -> Image.Image | None:
    """Render an HICON on black and white to recover exact alpha for any icon format."""
    import numpy as np
    black = _render_icon(hicon, size, 0x00)
    white = _render_icon(hicon, size, 0xFF)
    if black is None or white is None:
        return None
    b = np.frombuffer(black, np.uint8).reshape(size, size, 4)[:, :, :3].astype(np.float32)
    w = np.frombuffer(white, np.uint8).reshape(size, size, 4)[:, :, :3].astype(np.float32)
    alpha = 1.0 - np.clip((w - b).mean(axis=2) / 255.0, 0.0, 1.0)
    rgb = np.where(alpha[..., None] > 1e-3, b / np.maximum(alpha[..., None], 1e-3), 0)
    out = np.dstack([rgb[:, :, 2], rgb[:, :, 1], rgb[:, :, 0], alpha * 255.0])
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGBA")


def _icon_index(path: str, is_dir: bool, by_attributes: bool) -> tuple[int, str] | None:
    info = SHFILEINFOW()
    flags = SHGFI_SYSICONINDEX | SHGFI_TYPENAME
    attrs = FILE_ATTRIBUTE_DIRECTORY if is_dir else FILE_ATTRIBUTE_NORMAL
    if by_attributes:
        flags |= SHGFI_USEFILEATTRIBUTES
    res = shell32.SHGetFileInfoW(path, attrs, ctypes.byref(info), ctypes.sizeof(info), flags)
    if not res:
        return None
    return info.iIcon, info.szTypeName


def _icon_from_list(index: int, shil: int):
    il = ctypes.c_void_p()
    if shell32.SHGetImageList(shil, ctypes.byref(IID_IImageList), ctypes.byref(il)) != 0 or not il:
        return None
    hicon = wintypes.HICON()
    get_icon = _vtable_fn(il, 10, HRESULT, ctypes.c_int, wintypes.UINT, ctypes.POINTER(wintypes.HICON))
    hr = get_icon(il, index, ILD_TRANSPARENT, ctypes.byref(hicon))
    _release(il)
    return hicon if hr == 0 and hicon else None


def system_icon(path: str, is_dir: bool, size: int = 64, by_attributes: bool = False) -> tuple[Image.Image, str] | None:
    """(RGBA icon, shell type name) for a path; by_attributes=True avoids touching the file."""
    if not IS_WINDOWS:
        return None
    try:
        res = _icon_index(path, is_dir, by_attributes)
        if res is None:
            return None
        index, type_name = res
        img = None
        hicon = _icon_from_list(index, SHIL_JUMBO)
        if hicon:
            img = hicon_to_image(hicon, 256)
            user32.DestroyIcon(hicon)
            if img is not None:
                bbox = img.getbbox()
                # old-style icons only fill the top-left 48 px of the jumbo canvas
                if bbox is None or (bbox[2] - bbox[0] <= 64 and bbox[3] - bbox[1] <= 64):
                    img = None
        if img is None:
            hicon = _icon_from_list(index, SHIL_EXTRALARGE)
            if not hicon:
                return None
            img = hicon_to_image(hicon, 48)
            user32.DestroyIcon(hicon)
            if img is None:
                return None
        img = img.resize((size, size), Image.LANCZOS)
        return img, type_name
    except Exception:
        return None


def _hbitmap_to_image(hbmp) -> Image.Image | None:
    import numpy as np
    bm = BITMAP()
    if not gdi32.GetObjectW(hbmp, ctypes.sizeof(BITMAP), ctypes.byref(bm)):
        return None
    w, h = bm.bmWidth, abs(bm.bmHeight)
    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth, bmi.biHeight, bmi.biPlanes, bmi.biBitCount = w, -h, 1, 32
    buf = ctypes.create_string_buffer(w * h * 4)
    hdc = gdi32.CreateCompatibleDC(None)
    lines = gdi32.GetDIBits(hdc, hbmp, 0, h, buf, ctypes.byref(bmi), 0)
    gdi32.DeleteDC(hdc)
    if lines != h:
        return None
    arr = np.frombuffer(buf.raw, np.uint8).reshape(h, w, 4).copy()
    arr = arr[:, :, [2, 1, 0, 3]]
    if arr[:, :, 3].max() == 0:
        arr[:, :, 3] = 255
    return Image.fromarray(arr, "RGBA")


def shell_thumbnail(path: str, size: int = 256, thumbnail_only: bool = True) -> Image.Image | None:
    """Explorer thumbnail for a file (videos, images, documents with handlers)."""
    if not IS_WINDOWS:
        return None
    factory = ctypes.c_void_p()
    try:
        hr = shell32.SHCreateItemFromParsingName(path, None, ctypes.byref(IID_IShellItemImageFactory), ctypes.byref(factory))
        if hr != 0 or not factory:
            return None
        get_image = _vtable_fn(factory, 3, HRESULT, SIZE, ctypes.c_int, ctypes.POINTER(wintypes.HBITMAP))
        hbmp = wintypes.HBITMAP()
        flags = SIIGBF_THUMBNAILONLY if thumbnail_only else SIIGBF_RESIZETOFIT
        hr = get_image(factory, SIZE(size, size), flags, ctypes.byref(hbmp))
        if hr != 0 or not hbmp:
            return None
        img = _hbitmap_to_image(hbmp)
        gdi32.DeleteObject(hbmp)
        return img
    except Exception:
        return None
    finally:
        _release(factory)
