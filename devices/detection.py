"""Storage device discovery and hot-plug monitoring."""
from __future__ import annotations

import threading

import psutil
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from filesystem.threads import safe_emit

from .storage_info import DeviceInfo, describe_device, logical_drive_mask, query_media_types


def list_devices(include_media_query: bool = True) -> list[DeviceInfo]:
    media_map = query_media_types() if include_media_query else {}
    seen: set[str] = set()
    devices: list[DeviceInfo] = []
    try:
        parts = psutil.disk_partitions(all=True)
    except Exception:
        parts = []
    for p in parts:
        mount = p.mountpoint or p.device
        if not mount or mount.upper() in seen:
            continue
        seen.add(mount.upper())
        try:
            devices.append(describe_device(mount, p.fstype, media_map))
        except Exception as exc:  # never let one odd device break discovery
            devices.append(DeviceInfo(mount=mount, letter=mount[:2], error=str(exc), ready=False))
    devices.sort(key=lambda d: d.mount.upper())
    return devices


class DeviceMonitor(QObject):
    """Polls the logical drive bitmask cheaply and rescans devices on change."""

    devices_changed = pyqtSignal(list)    # list[DeviceInfo]

    def __init__(self, interval_ms: int = 2000, parent=None):
        super().__init__(parent)
        self._mask = -1
        self._busy = False
        self._force = False
        self.devices: list[DeviceInfo] = []
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(interval_ms)
        self._ticks = 0

    def start(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        self._force = True
        self._poll()

    def _poll(self) -> None:
        self._ticks += 1
        mask = logical_drive_mask()
        # also refresh capacity occasionally (every ~30 s) and on demand
        if mask == self._mask and not self._force and self._ticks % 15 != 0:
            return
        if self._busy:
            return
        self._mask = mask
        self._force = False
        self._busy = True
        threading.Thread(target=self._scan, daemon=True, name="device-scan").start()

    def _scan(self) -> None:
        try:
            from .storage_info import _media_cache
            if _media_cache is None:
                # fast first pass; the SSD/HDD/bus query (PowerShell) follows
                safe_emit(self.devices_changed, list_devices(include_media_query=False))
            devices = list_devices()
        except Exception:
            devices = []
        self._busy = False
        safe_emit(self.devices_changed, devices)
