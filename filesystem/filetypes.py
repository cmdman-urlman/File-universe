"""File type classification by extension (no file contents are read)."""
from __future__ import annotations

import os

CATEGORY_EXTENSIONS: dict[str, set[str]] = {
    "image": {"jpg", "jpeg", "png", "webp", "gif", "bmp", "tif", "tiff", "ico", "heic", "svg", "raw", "cr2", "nef", "psd"},
    "video": {"mp4", "mkv", "avi", "mov", "wmv", "webm", "flv", "m4v", "mpg", "mpeg", "3gp", "ts"},
    "audio": {"mp3", "wav", "flac", "ogg", "m4a", "aac", "wma", "opus", "aiff", "mid", "midi"},
    "archive": {"zip", "rar", "7z", "tar", "gz", "bz2", "xz", "iso", "cab", "zst", "tgz"},
    "document": {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "rtf", "txt", "md", "csv", "epub"},
    "code": {"py", "js", "ts", "c", "cpp", "h", "hpp", "cs", "java", "go", "rs", "rb", "php", "html", "css", "json",
             "xml", "yml", "yaml", "toml", "ini", "sh", "ps1", "bat", "cmd", "sql", "lua", "kt", "swift"},
    "executable": {"exe", "msi", "dll", "sys", "com", "scr", "appx", "msix", "lnk"},
    "font": {"ttf", "otf", "woff", "woff2", "fon"},
    "model3d": {"obj", "fbx", "stl", "blend", "gltf", "glb", "3ds"},
    "database": {"db", "sqlite", "mdb", "accdb", "dat", "bin"},
}

_EXT_TO_CATEGORY = {ext: cat for cat, exts in CATEGORY_EXTENSIONS.items() for ext in exts}

CATEGORY_LABELS = {
    "image": "Image", "video": "Video", "audio": "Audio", "archive": "Archive",
    "document": "Document", "code": "Source / text", "executable": "Program / library",
    "font": "Font", "model3d": "3D model", "database": "Data file", "other": "File",
}

# RGB colours (0..1) used consistently in the 3D scene, icons and lists.
CATEGORY_COLORS: dict[str, tuple[float, float, float]] = {
    "image": (0.95, 0.40, 0.85),
    "video": (1.00, 0.35, 0.30),
    "audio": (0.35, 0.95, 0.50),
    "archive": (1.00, 0.65, 0.20),
    "document": (0.40, 0.65, 1.00),
    "code": (0.30, 0.95, 0.95),
    "executable": (1.00, 0.90, 0.30),
    "font": (0.80, 0.70, 1.00),
    "model3d": (0.60, 1.00, 0.80),
    "database": (0.75, 0.75, 0.55),
    "other": (0.85, 0.88, 0.95),
}

PREVIEWABLE_IMAGES = {"jpg", "jpeg", "png", "webp", "gif", "bmp"}


def extension(name: str) -> str:
    ext = os.path.splitext(name)[1]
    return ext[1:].lower() if ext else ""


def category_for(name: str) -> str:
    return _EXT_TO_CATEGORY.get(extension(name), "other")


def type_description(name: str) -> str:
    ext = extension(name)
    label = CATEGORY_LABELS[category_for(name)]
    return f"{label} (.{ext})" if ext else label
