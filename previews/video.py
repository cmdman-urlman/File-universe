"""Video thumbnails: ffmpeg/ffprobe when available, Explorer thumbnails otherwise.

ffmpeg is run as a separate process without a shell, reading the file as data
and writing a single PNG frame to stdout. Nothing is executed from the file.
"""
from __future__ import annotations

import io
import json
import shutil
import subprocess

from PIL import Image

from filesystem.paths import os_path

_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def ffprobe_path() -> str | None:
    return shutil.which("ffprobe")


def probe(path: str, timeout: float = 6.0) -> dict:
    exe = ffprobe_path()
    if not exe:
        return {}
    try:
        out = subprocess.run([exe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", os_path(path)],
                             capture_output=True, timeout=timeout, creationflags=_FLAGS)
        data = json.loads(out.stdout.decode("utf-8", "replace") or "{}")
    except Exception:
        return {}
    info: dict = {}
    fmt = data.get("format", {})
    try:
        info["duration"] = float(fmt.get("duration"))
    except (TypeError, ValueError):
        pass
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and "width" not in info:
            info["width"], info["height"] = s.get("width"), s.get("height")
            info["video_codec"] = s.get("codec_name")
        elif s.get("codec_type") == "audio" and "audio_codec" not in info:
            info["audio_codec"] = s.get("codec_name")
            info["sample_rate"] = s.get("sample_rate")
            info["channels"] = s.get("channels")
    return info


def extract_frame(path: str, max_size: int = 320, at_seconds: float = 1.0, timeout: float = 10.0) -> Image.Image | None:
    exe = ffmpeg_path()
    if exe:
        cmd = [exe, "-v", "error", "-ss", str(at_seconds), "-i", os_path(path), "-frames:v", "1",
               "-vf", f"scale='min({max_size},iw)':-2", "-f", "image2pipe", "-vcodec", "png", "-"]
        try:
            out = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=_FLAGS)
            if not out.stdout and at_seconds > 0:
                cmd[4] = "0"
                out = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=_FLAGS)
            if out.stdout:
                return Image.open(io.BytesIO(out.stdout)).convert("RGBA")
        except Exception:
            pass
    try:
        from icons.windows_icons import shell_thumbnail
        return shell_thumbnail(path, max_size)
    except Exception:
        return None
