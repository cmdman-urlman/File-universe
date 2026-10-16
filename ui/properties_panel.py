"""Right-hand properties panel for the selected object (or current location)."""
from __future__ import annotations

import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QGuiApplication
from PyQt6.QtWidgets import (QFormLayout, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
                             QVBoxLayout, QWidget)

from devices.storage_info import DeviceInfo
from filesystem.filetypes import type_description
from filesystem.models import FSNode, ScanState
from universe.hierarchy import cosmic_name, file_cosmic_name
from universe.mapping import format_size, visual_radius

from .qt_images import pil_to_pixmap


def _fmt_time(ts: float | None) -> str:
    if ts is None:
        return "unknown"
    try:
        return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return "unknown"


def _exact(n: int | None) -> str:
    if n is None:
        return "unknown"
    return f"{format_size(n)} ({n:,} bytes)" if n >= 1024 else f"{n:,} bytes"


class PropertiesPanel(QWidget):
    def __init__(self, icon_pixmaps, preview_service, parent=None):
        super().__init__(parent)
        self.pixmaps = icon_pixmaps
        self.previews = preview_service
        self.setMinimumWidth(260)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        self.lay = QVBoxLayout(body)
        head = QHBoxLayout()
        self.icon = QLabel()
        self.icon.setFixedSize(48, 48)
        head.addWidget(self.icon)
        self.title = QLabel("Nothing selected")
        self.title.setWordWrap(True)
        self.title.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        head.addWidget(self.title, 1)
        self.lay.addLayout(head)
        self.cosmic = QLabel("")
        self.cosmic.setStyleSheet("color: #8fb8ff;")
        self.lay.addWidget(self.cosmic)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.preview.setStyleSheet("background:#0b1220; border-radius:6px;")
        self.preview.hide()
        self.lay.addWidget(self.preview)
        self.form_host = QWidget()
        self.form = QFormLayout(self.form_host)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.lay.addWidget(self.form_host)
        self.copy_btn = QPushButton("Copy path")
        self.copy_btn.clicked.connect(self._copy)
        self.lay.addWidget(self.copy_btn)
        self.lay.addStretch(1)
        self._path = None
        self._payload = None
        self._depth = 0
        self._is_current = False
        self.previews.preview_ready.connect(self._on_preview)

    def _row(self, key: str, value: str) -> None:
        v = QLabel(value)
        v.setWordWrap(True)
        v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.form.addRow(f"<span style='color:#9aa7c0'>{key}</span>", v)

    def _clear(self) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        self.preview.hide()
        self.preview.clear()

    def _copy(self) -> None:
        if self._path:
            QGuiApplication.clipboard().setText(self._path)

    def show_payload(self, payload, depth: int = 0, is_current: bool = False, icon_key: str | None = None) -> None:
        """depth: cosmic depth of the payload's *container* scene."""
        self._payload, self._depth = payload, depth
        self._is_current = is_current
        if icon_key is None:
            icon_key = getattr(self, "_icon_key", None) if payload is getattr(self, "_icon_payload", None) else None
        self._icon_key, self._icon_payload = icon_key, payload
        self._clear()
        if icon_key:
            ic = self.pixmaps.icon(icon_key)
            self.icon.setPixmap(ic.pixmap(48, 48))
        else:
            self.icon.clear()
        if payload is None:
            self.title.setText("This PC")
            self.cosmic.setText("The multiverse — every storage device is a universe")
            self._path = None
            self._row("Hint", "Double-click a device (or pick it in the sidebar) to enter its universe.")
            return
        if isinstance(payload, DeviceInfo):
            self._show_device(payload)
        elif isinstance(payload, FSNode):
            self._show_node(payload, depth, is_current)

    def refresh(self) -> None:
        if self._payload is not None:
            self.show_payload(self._payload, self._depth, self._is_current)

    def _show_device(self, d: DeviceInfo) -> None:
        self._path = d.mount
        self.title.setText(d.title)
        self.cosmic.setText(f"Universe shaped like a {d.kind_label.lower()}")
        self._row("Drive", d.letter or d.mount)
        self._row("Label", d.label or "(none)")
        self._row("Device type", d.kind_label + (f" ({d.bus})" if d.bus else ""))
        if d.extra.get("model"):
            self._row("Model", d.extra["model"])
        self._row("File system", d.fstype or "unknown")
        if d.ready and d.total:
            self._row("Capacity", _exact(d.total))
            pct = 100.0 * (d.used or 0) / d.total
            self._row("Used", f"{_exact(d.used)} — {pct:.1f}%")
            self._row("Free", _exact(d.free))
        else:
            self._row("Status", d.error or "Not ready")

    def _show_node(self, n: FSNode, depth: int, is_current: bool) -> None:
        self._is_current = is_current
        self._path = n.path
        self.title.setText(n.name)
        if n.is_dir:
            cd = depth if is_current else depth + 1
            self.cosmic.setText(f"Folder shown as: {cosmic_name(cd)}" + ("  (you are here)" if is_current else ""))
        else:
            self.cosmic.setText(f"File shown as: {file_cosmic_name(depth)}")
        self._row("Full path", n.path)
        if n.is_dir:
            self._row("Type", "Folder" + (" (link / junction — not followed)" if n.is_link else ""))
            size = n.effective_size()
            label = _exact(size)
            if not n.size_complete:
                label = "≈ " + label + " (estimate, still measuring)" if n.total_size is not None else "not measured yet"
            self._row("Total size", label)
            if n.file_count is not None:
                self._row("Files (recursive)", f"{n.file_count:,}")
                self._row("Sub-folders (recursive)", f"{n.dir_count or 0:,}")
            if n.children is not None:
                f, d = n.direct_counts()
                self._row("Direct contents", f"{f:,} files, {d:,} folders")
            elif n.preview_total:
                self._row("Direct contents", f"≈ {n.preview_total:,} entries (not fully listed)")
            state = n.list_state.value
            if n.list_state == ScanState.UNSCANNED and n.size_complete:
                state = "sizes measured; contents listed on entry"
            self._row("Scan status", state)
            if n.size_errors:
                self._row("Inaccessible", f"{n.size_errors:,} folders/entries skipped (permission denied)")
            self._row("Visual radius", f"{visual_radius(size, True):.2f} units (log scale)")
        else:
            self._row("Type", type_description(n.name))
            self._row("Extension", f".{n.extension}" if n.extension else "(none)")
            self._row("Size", _exact(n.size))
            self._row("Visual radius", f"{visual_radius(n.size):.2f} units (log scale)")
            pv = self.previews.get(n.path)
            if pv is None:
                if n.category in ("image", "video", "audio"):
                    self.previews.request(n.path)
                    self._row("Preview", "loading…")
            else:
                self._apply_preview(pv)
        self._row("Modified", _fmt_time(n.mtime))
        if n.hidden:
            self._row("Attributes", "hidden")
        if n.error:
            self._row("Error", n.error)

    def _apply_preview(self, pv) -> None:
        for k, v in pv.info.items():
            self._row(k, v)
        if pv.image is not None:
            pm = pil_to_pixmap(pv.image)
            w = max(200, self.width() - 30)
            pm = pm.scaledToWidth(min(w, pm.width() * 2), Qt.TransformationMode.SmoothTransformation)
            if pm.height() > 260:
                pm = pm.scaledToHeight(260, Qt.TransformationMode.SmoothTransformation)
            self.preview.setPixmap(pm)
            self.preview.setFixedHeight(pm.height() + 8)
            self.preview.show()
        elif pv.kind == "audio":
            self._row("Preview", "waveform unavailable (install ffmpeg for non-WAV audio)")

    def _on_preview(self, path: str) -> None:
        if isinstance(self._payload, FSNode) and self._payload.path == path:
            self.show_payload(self._payload, self._depth, getattr(self, "_is_current", False))
