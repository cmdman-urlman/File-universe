"""Storage device metadata: capacity, labels, drive and media types.

Uses psutil for partitions/capacity, the Win32 API (via ctypes) for volume
labels and drive types, and - once, in the background - PowerShell's
``Get-PhysicalDisk`` to tell SSDs from HDDs and USB/SD bus types. Everything
degrades gracefully when information is unavailable.
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field

import psutil

IS_WINDOWS = sys.platform == "win32"

# Win32 GetDriveType values
DRIVE_UNKNOWN, DRIVE_NO_ROOT_DIR, DRIVE_REMOVABLE, DRIVE_FIXED, DRIVE_REMOTE, DRIVE_CDROM, DRIVE_RAMDISK = range(7)

# Device kinds -> universe shapes
SSD, HDD, USB, DISC, SDCARD, NETWORK, RAMDISK, UNKNOWN = "ssd", "hdd", "usb", "disc", "sd", "network", "ram", "unknown"

KIND_LABELS = {
    SSD: "Solid-state drive", HDD: "Hard disk drive", USB: "USB flash drive",
    DISC: "Optical disc", SDCARD: "SD / memory card", NETWORK: "Network drive",
    RAMDISK: "RAM disk", UNKNOWN: "Storage device",
}


@dataclass
class DeviceInfo:
    mount: str                      # e.g. "C:\\"
    letter: str = ""
    label: str = ""
    fstype: str = ""
    drive_type: int = DRIVE_UNKNOWN
    kind: str = UNKNOWN
    bus: str = ""
    media: str = ""
    total: int | None = None
    used: int | None = None
    free: int | None = None
    ready: bool = True              # False e.g. for an empty DVD drive
    error: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def title(self) -> str:
        name = self.label or KIND_LABELS.get(self.kind, "Drive")
        return f"{name} ({self.letter or self.mount})"

    @property
    def key(self) -> str:
        from filesystem.paths import norm_key
        return norm_key(self.mount)

    @property
    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind, "Storage device")


def _set_error_mode() -> None:
    """Suppress 'insert a disk' dialogs when probing empty removable drives."""
    if IS_WINDOWS:
        try:
            ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x8000)  # FAILCRITICALERRORS | NOOPENFILEERRORBOX
        except Exception:
            pass


_set_error_mode()


def drive_type(mount: str) -> int:
    if not IS_WINDOWS:
        return DRIVE_FIXED
    try:
        return int(ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(mount)))
    except Exception:
        return DRIVE_UNKNOWN


def logical_drive_mask() -> int:
    if not IS_WINDOWS:
        return 0
    try:
        return int(ctypes.windll.kernel32.GetLogicalDrives())
    except Exception:
        return 0


def volume_info(mount: str) -> tuple[str, str] | None:
    """(label, filesystem) or None if no media / unavailable."""
    if not IS_WINDOWS:
        return None
    label = ctypes.create_unicode_buffer(261)
    fs = ctypes.create_unicode_buffer(261)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(
        ctypes.c_wchar_p(mount), label, 261, None, None, None, fs, 261)
    if not ok:
        return None
    return label.value, fs.value


_media_cache: dict[str, dict] | None = None


def query_media_types(timeout: float = 8.0) -> dict[str, dict]:
    """Map drive letter -> {'media': 'SSD'|'HDD'|..., 'bus': 'USB'|'SD'|...}.

    Runs PowerShell once (no admin rights needed) and caches the answer.
    """
    global _media_cache
    if _media_cache is not None:
        return _media_cache
    result: dict[str, dict] = {}
    if IS_WINDOWS:
        script = (
            "$ErrorActionPreference='SilentlyContinue';"
            "$pd=@{}; Get-PhysicalDisk | ForEach-Object { $pd[[string]$_.DeviceId]=$_ };"
            "Get-Partition | Where-Object { $_.DriveLetter } | ForEach-Object {"
            " $d=$pd[[string]$_.DiskNumber];"
            " [pscustomobject]@{L=[string]$_.DriveLetter; M=[string]$d.MediaType; B=[string]$d.BusType;"
            " N=[string]$d.FriendlyName} } | ConvertTo-Json -Compress"
        )
        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                                 capture_output=True, text=True, timeout=timeout, creationflags=flags)
            data = json.loads(out.stdout) if out.stdout.strip() else []
            if isinstance(data, dict):
                data = [data]
            for row in data:
                letter = (row.get("L") or "").strip().upper()
                if letter:
                    result[letter] = {"media": row.get("M") or "", "bus": row.get("B") or "",
                                      "model": row.get("N") or ""}
        except Exception:
            result = {}
    _media_cache = result
    return result


def classify(dtype: int, media: str, bus: str, model: str = "") -> str:
    media_l, bus_l, model_l = media.lower(), bus.lower(), model.lower()
    if dtype == DRIVE_CDROM:
        return DISC
    if dtype == DRIVE_REMOTE:
        return NETWORK
    if dtype == DRIVE_RAMDISK:
        return RAMDISK
    if bus_l == "sd" or "sd card" in model_l or "sdxc" in model_l or "sdhc" in model_l or "card reader" in model_l:
        return SDCARD
    if dtype == DRIVE_REMOVABLE:
        return USB
    if bus_l == "usb":
        return USB if media_l != "hdd" else HDD
    if media_l == "hdd":
        return HDD
    if media_l == "ssd" or bus_l == "nvme":
        return SSD
    if dtype == DRIVE_FIXED:
        return SSD
    return UNKNOWN


def describe_device(mount: str, fstype: str = "", media_map: dict | None = None) -> DeviceInfo:
    letter = mount[:2].upper() if len(mount) >= 2 and mount[1] == ":" else ""
    info = DeviceInfo(mount=mount, letter=letter, fstype=fstype)
    info.drive_type = drive_type(mount)
    media = (media_map or {}).get(letter[:1], {})
    info.media, info.bus = media.get("media", ""), media.get("bus", "")
    info.extra["model"] = media.get("model", "")
    info.kind = classify(info.drive_type, info.media, info.bus, info.extra["model"])
    vi = volume_info(mount)
    if vi is not None:
        info.label, fs = vi
        info.fstype = info.fstype or fs
    elif info.drive_type in (DRIVE_CDROM, DRIVE_REMOVABLE):
        info.ready = False
        info.error = "No media inserted"
        return info
    if info.drive_type == DRIVE_REMOTE or info.ready:
        try:
            usage = psutil.disk_usage(mount)
            info.total, info.used, info.free = usage.total, usage.used, usage.free
        except OSError as exc:
            info.error = exc.strerror or str(exc)
            info.ready = info.drive_type != DRIVE_CDROM and os.path.isdir(mount)
    return info
