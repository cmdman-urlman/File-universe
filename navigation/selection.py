"""Selection state shared by the 3D view, the object list and the properties panel."""
from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal


class SelectionModel(QObject):
    changed = pyqtSignal(object)          # payload (FSNode / DeviceInfo) or None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.payload: Any = None
        self.pending_key: str | None = None   # select this path once its listing arrives

    def set(self, payload: Any) -> None:
        if payload is self.payload:
            return
        self.payload = payload
        self.changed.emit(payload)

    def clear(self) -> None:
        self.set(None)
