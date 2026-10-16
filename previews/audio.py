"""Audio waveform previews (never plays audio).

WAV files are decoded with the standard library; other formats are decoded to
a low-rate mono PCM stream by ffmpeg when it is installed.
"""
from __future__ import annotations

import subprocess
import wave

import numpy as np
from PIL import Image, ImageDraw

from filesystem.paths import os_path

from .video import _FLAGS, ffmpeg_path

MAX_SECONDS = 120
RATE = 8000


def _wav_samples(path: str) -> tuple[np.ndarray, float] | None:
    try:
        with wave.open(os_path(path), "rb") as w:
            ch, width, rate, frames = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
            duration = frames / float(rate or 1)
            raw = w.readframes(min(frames, rate * MAX_SECONDS))
        dtype = {1: np.uint8, 2: np.int16, 4: np.int32}.get(width)
        if dtype is None:
            return None
        data = np.frombuffer(raw, dtype).astype(np.float32)
        if width == 1:
            data -= 128
        if ch > 1:
            data = data[: len(data) // ch * ch].reshape(-1, ch).mean(axis=1)
        return data, duration
    except Exception:
        return None


def _ffmpeg_samples(path: str, timeout: float = 15.0) -> tuple[np.ndarray, float] | None:
    exe = ffmpeg_path()
    if not exe:
        return None
    cmd = [exe, "-v", "error", "-t", str(MAX_SECONDS), "-i", os_path(path), "-ac", "1", "-ar", str(RATE),
           "-f", "s16le", "-"]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=_FLAGS)
        data = np.frombuffer(out.stdout, np.int16).astype(np.float32)
        if len(data) == 0:
            return None
        return data, len(data) / RATE
    except Exception:
        return None


def waveform_envelope(samples: np.ndarray, bins: int = 300) -> np.ndarray:
    if len(samples) == 0:
        return np.zeros(bins)
    n = len(samples) // bins * bins
    if n == 0:
        return np.abs(samples[:bins]) / max(np.abs(samples).max(), 1e-9)
    env = np.abs(samples[:n]).reshape(bins, -1).max(axis=1)
    return env / max(env.max(), 1e-9)


def waveform_image(path: str, size: tuple[int, int] = (320, 110)) -> tuple[Image.Image | None, float | None]:
    res = _wav_samples(path) if path.lower().endswith(".wav") else None
    if res is None:
        res = _ffmpeg_samples(path)
    if res is None:
        return None, None
    samples, duration = res
    w, h = size
    env = waveform_envelope(samples, w // 2)
    img = Image.new("RGBA", size, (12, 18, 30, 255))
    d = ImageDraw.Draw(img)
    mid = h / 2
    for i, v in enumerate(env):
        x = i * 2
        a = v * (h / 2 - 6)
        t = i / max(len(env) - 1, 1)
        col = (int(60 + 120 * t), int(230 - 80 * t), int(140 + 100 * t), 255)
        d.line([(x, mid - a), (x, mid + a)], fill=col, width=1)
    d.line([(0, mid), (w, mid)], fill=(60, 80, 110, 255))
    return img, duration
